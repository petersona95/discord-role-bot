import discord, asyncio
from discord import app_commands
from discord.ext import commands
from discord import ui # modals
from table2ascii import table2ascii as t2a, PresetStyle
import os

from discord.interactions import Interaction # used to define dev/prod token

# py files
import gcp_secrets # function to retrieve discord private key from gcp secret manager
import firestore # used to talk to firestore
import gcp_translate # translating in google translation api
import logger # used to write logs to google log explorer as well as to stdout


intents = discord.Intents.default()
intents.members = True # required for removing roles
intents.message_content = True # required for slash commands

# create connection
bot = commands.Bot(command_prefix="!", intents=intents)

# determine token based on environment variable
env = os.getenv('env')
# ID of the secret to create.
if env=='dev':
    secretName = "discord-role-bot-token-dev"
elif env=='prod':
    secretName = "discord-role-bot-token"
token = gcp_secrets.get_secret_contents(secretName)


@bot.event # decorator
async def on_ready():
    logger.write_log(
        action=None,
        payload='Bot has logged in.',
        severity='Debug'
    )    
    try:
        bot.add_view(ViewAllianceSelection())
        # syncing is used for /commands
        # Its used to show /command options available for users in discord itself. They're called trees in discord
        # by not defining a guild_id its considered a global tree. it can take up to 24 hours to refresh on servers
        # BUG: I shouldn't have this here because every time the shard invalidates it re-syncs the functions.
        '''
        2023-04-20 22:36:42 INFO     discord.gateway Shard ID None session has been invalidated.
        2023-04-20 22:36:47 INFO     discord.gateway Shard ID None has connected to Gateway (Session ID: 08fa2f592630f7558353482ffbd1f724).
        bot is logged in
        synced 2 command(s)
        '''
        synced = await bot.tree.sync()
        logger.write_log(
            action=None,
            payload=f"synced {len(synced)} command(s)",
            severity='Debug'
        )

    except Exception as e:
        logger.write_log(
            action=None,
            payload=str(e),
            severity='Error'
        )

# views
class ViewAllianceSelection(discord.ui.View):
    def __init__(self):
        super().__init__(timeout = None)
    @discord.ui.button(label = "NONA", custom_id = "Role 1", style = discord.ButtonStyle.blurple)
    async def NONA(self, interaction: discord.Interaction, button:discord.Button):
        await interaction.response.send_modal(ModalApplicationForm(roleName='NONA'))
    @discord.ui.button(label = "TFM", custom_id = "Role 2", style = discord.ButtonStyle.green)
    async def TFM(self, interaction: discord.Interaction, button:discord.Button):
        await interaction.response.send_modal(ModalApplicationForm(roleName='TFM'))
    @discord.ui.button(label = "WP", custom_id = "Role 3", style = discord.ButtonStyle.red)
    async def WP(self, interaction: discord.Interaction, button:discord.Button):
        await interaction.response.send_modal(ModalApplicationForm(roleName='WP'))
    @discord.ui.button(label = "TCO", custom_id = "Role 4", style = discord.ButtonStyle.gray)
    async def TCO(self, interaction: discord.Interaction, button:discord.Button):
        await interaction.response.send_modal(ModalApplicationForm(roleName='TCO'))
    @discord.ui.button(label = "DLT", custom_id = "Role 5", style = discord.ButtonStyle.green)
    async def DLT(self, interaction: discord.Interaction, button:discord.Button):
        await interaction.response.send_modal(ModalApplicationForm(roleName='DLT'))


# modals
class ModalApplicationForm(discord.ui.Modal, title='Alliance Application Form'):
    def __init__(self, roleName):
        super().__init__(timeout = None) # required to pass variables into the class (roleName)
        self.roleName = roleName

    submittedUN = ui.TextInput(label='Enter your Travian username.', style=discord.TextStyle.short)
    async def on_submit(self, interaction: discord.Interaction):
        logger.write_log(
        action='Application Form',
        payload=f'User {str(interaction.user)} applied to {self.roleName}.',
        severity='Info'
        )
        try:
            # add or update user in firestore
            newUser = firestore.travianUser(userId=str(interaction.user.id), discordUsername=str(interaction.user), travianUsername=str(self.submittedUN).lower(),allianceRole=str(self.roleName), guildId=interaction.guild_id)
            status = newUser.add_user()
            if status == 'Rejected':
                await interaction.response.send_message(f'<@{interaction.user.id}>, you have already been rejected from joining the coalition. Please contact alliance leadership if you believe this to be a mistake.', ephemeral=True)
                logger.write_log(
                action='Application Form',
                payload=f'Firestore record handled successfully for user {str(interaction.user)}.',
                severity='Debug'
                )
                return      
            elif status == 'Approved':
                await interaction.response.send_message(f'<@{interaction.user.id}>, your application to **{self.roleName}** has been denied because you are already a part of an alliance. Please contact leadership if you believe this to be a mistake.', ephemeral=True)
                logger.write_log(
                action='Application Form',
                payload=f'Firestore record handled successfully for user {str(interaction.user)}.',
                severity='Debug'
                )
                return         
            elif status == 'Duplicate UN':
                await interaction.response.send_message(f'<@{interaction.user.id}>, your application to **{self.roleName}** has been denied because you chose a Travian username that is already registered with another member. Please contact leadership if you believe this to be a mistake.', ephemeral=True)
                logger.write_log(
                action='Application Form',
                payload=f'Firestore record handled successfully for user {str(interaction.user)}. User was marked REJECTED',
                severity='Debug'
                )
                return
            
        except Exception as e:
            logger.write_log(
                action=None,
                payload=str(e),
                severity='Error'
            )
            admin_user_id = gcp_secrets.get_secret_contents('discord-bot-admin-user-id')
            adminUser = interaction.guild.get_member(int(admin_user_id))
            await adminUser.send(f'An error occured in petebot; modalForm; {e}')
                       
        # alert admin channel
        try:
            channel = discord.utils.get(interaction.guild.channels, name=f"{str(self.roleName).lower()}-approvals")
            embed = discord.Embed(
                colour=discord.Color.dark_teal(),
                title='New alliance application. Please approve or reject this applicant with /approve OR /reject and their **Travian** username.'
                # description=f'Please approve or reject this applicant with /approve OR /reject'
            )
            embed.add_field(name='Travian Username', value=str(self.submittedUN).lower(), inline=False)
            embed.add_field(name='Discord Username', value=f'<@{interaction.user.id}>', inline=False)
            # send embed to admin channel
            await channel.send(f'<#{channel.id}>', embed=embed)
            # send message to applicant
            await interaction.response.send_message(f'Thank you <@{interaction.user.id}>, your application to **{self.roleName}** as user **{str(self.submittedUN).lower()}** has been submitted. Please wait to be approved by leadership.', ephemeral=True)
            logger.write_log(
                action='Application Form',
                payload=f'Approval message for user {str(interaction.user)} was handled successfully.',
                severity='Debug'
                )        
        except Exception as e:
            logger.write_log(
                action=None,
                payload=str(e),
                severity='Error'
            )
            admin_user_id = gcp_secrets.get_secret_contents('discord-bot-admin-user-id')
            adminUser = interaction.guild.get_member(int(admin_user_id))
            await adminUser.send(f'An error occured in petebot; modalForm; {e}')           

'''
Have the bot send the alliance pick message
'''
@bot.command()
async def pick_ally(ctx):
    embed = discord.Embed(
        colour=discord.Color.dark_teal(),
        title='Welcome to the Coalition',
        description='Press a button below to join your alliance.'
    )
    await ctx.send(embed=embed, view=ViewAllianceSelection())

'''
help commands
'''
@bot.command()
async def alliancehelp(ctx):
    embed = discord.Embed(
        colour=discord.Color.dark_teal(),
        title='The following commands are available to you',
    )
    embed.add_field(name='/approve [username] [alliance]', value='Used to approve an applicant to your alliance', inline=False)
    embed.add_field(name='/approve_all [alliance]', value='rather than approve members individually, you can approve all pending users in the queue', inline=False)
    embed.add_field(name='/pending [alliance]', value='shows all pending users in the queue', inline=False)
    embed.add_field(name='/reject [username] [alliance]', value='Rejects a player from joining your alliance. They will be marked as REJECTED and will be unable to join any alliance until this is corrected.', inline=False)
    await ctx.send(embed=embed)

'''
Show all pending invites to respective
'''
@bot.tree.command(name="pending", description="Show pending approvals for a specific alliance")
@app_commands.choices(alliance=[
        app_commands.Choice(name="DLT", value="DLT"),
        app_commands.Choice(name="NONA", value="NONA"),
        app_commands.Choice(name="TFM", value="TFM"),
        app_commands.Choice(name="TCO", value="TCO"),
        app_commands.Choice(name="WP", value="WP")
        ])
async def pending(interaction: discord.Interaction, alliance: app_commands.Choice[str]):
    logger.write_log(
    action='/pending',
    payload=f'User {interaction.user} invoked the /approve command for {alliance.value}.',
    severity='Debug'
    )
    # get leader / ally roles and ensure user has permission to use command
    try:
        leaderRole = discord.utils.get(interaction.guild.roles, name='LEADER-'+str(alliance.value).upper())
        allyRole = discord.utils.get(interaction.guild.roles, name=str(alliance.value).upper())
    except Exception as e:
        logger.write_log(
            action=None,
            payload=str(e),
            severity='Error'
        )
        admin_user_id = gcp_secrets.get_secret_contents('discord-bot-admin-user-id')
        adminUser = interaction.guild.get_member(int(admin_user_id))
        await adminUser.send(f'An error occured in petebot; command /pending; {e}')
    # check if command caller has leader role
    if leaderRole.id not in [y.id for y in interaction.user.roles]:
        await interaction.response.send_message(f"Hello <@{interaction.user.id}>. You do not have permission to use this command for <@&{allyRole.id}>. If you believe this is an error please contact admin.")
        return

    # get list of pending users and send as ascii message
    try:
        embed = discord.Embed(
            colour=discord.Color.dark_teal(),
            title='The following applicants are pending',
            description='use /approve and /reject to resolve applications for individual members or /approve_all to approve everyone on this list.'
        )
        output = ''
        userList = firestore.get_pending_users(interaction.guild_id, str(alliance.value).upper())
        if userList: # check if any records returned
            for user in userList: # will iterate over one dictionary entry
                output+= f"- **{user['travianUsername']}** | {user['discordUsername']}\n"
        else:
            await interaction.response.send_message(f"There are no pending applicants for <@&{allyRole.id}>.")
            return
 
        embed.add_field(name='Players', value=output, inline=False)
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        logger.write_log(
            action=None,
            payload=str(e),
            severity='Error'
        )
        admin_user_id = gcp_secrets.get_secret_contents('discord-bot-admin-user-id')
        adminUser = interaction.guild.get_member(int(admin_user_id))
        await adminUser.send(f'An error occured in petebot; command /pending; {e}')

'''
/APPROVE_ALL
Approve everyone
'''
@bot.tree.command(name="approve_all", description="Approve all pending members to the alliance")
@app_commands.choices(alliance=[
        app_commands.Choice(name="DLT", value="DLT"),
        app_commands.Choice(name="NONA", value="NONA"),
        app_commands.Choice(name="TFM", value="TFM"),
        app_commands.Choice(name="TCO", value="TCO"),
        app_commands.Choice(name="WP", value="WP")
        ])
async def approve_all(interaction: discord.Interaction, alliance: app_commands.Choice[str]):
    logger.write_log(
    action='/approve_all',
    payload=f'User {interaction.user} invoked the /approve_all command for {alliance.value}.',
    severity='Debug'
    )

    # get leader / ally roles and ensure user has permission to use the command
    try:
        # message can take longer than 3 second timeout. defer
        await interaction.response.defer()

        leaderRole = discord.utils.get(interaction.guild.roles, name='LEADER-'+str(alliance.value).upper())
        allyRole = discord.utils.get(interaction.guild.roles, name=str(alliance.value).upper())
    except Exception as e:
        logger.write_log(
            action=None,
            payload=str(e),
            severity='Error'
        )
        admin_user_id = gcp_secrets.get_secret_contents('discord-bot-admin-user-id')
        adminUser = interaction.guild.get_member(int(admin_user_id))
        await adminUser.send(f'An error occured in petebot; command /approve_all; {e}')
        # end deferral of user on error
        await interaction.followup.send(f"Hello <@{interaction.user.id}>. This command has failed. A notification has been sent to admin to investigate.")
        # check if command caller has leader role
    if leaderRole.id not in [y.id for y in interaction.user.roles]:
        await interaction.followup.send(f"Hello <@{interaction.user.id}>. You do not have permission to approve users for <@&{allyRole.id}>. If you believe this is an error please contact admin.")
        return

    # approve all users who have alliance role and are pending
    try:
        embed = discord.Embed(
            colour=discord.Color.dark_teal(),
            title='The following members have been successfully approved:'
        )
        output = ''
        payloadBody = []
        userList = firestore.approve_all_users(guildId=interaction.guild_id, allianceRole=str(alliance.value).upper())

        # if users exist in firestore
        if userList: # check if any records returned
            logger.write_log(
            action='/approve_all',
            payload=f'Found pending users with allianceRole: {alliance.value}.',
            severity='Debug'
            )
            
            for user in userList: # will iterate over one dictionary entry
                # body for table response
                output+= f"- **{user['travianUsername']}** | {user['discordUsername']}\n"
                # body for logging payload
                payloadBody.append({user['travianUsername'], user['discordUsername']})
                targetMember = interaction.guild.get_member(int(user['userId']))
                # grant them the role
                await targetMember.add_roles(allyRole)
                # update their nickname
                await targetMember.edit(nick=f'[{allyRole}] {user["travianUsername"]}')
                logger.write_log(
                action='/approve',
                payload=f'Approved user with discordUsername: {user["discordUsername"]} and Travian UN: {user["travianUsername"]} to alliance: {alliance.value}',
                severity='Info'
                )
            embed.add_field(name='Players', value=output)
            await interaction.followup.send(embed=embed)
            logger.write_log(
            action='/approve_all',
            payload=f'Approved multiple users: {payloadBody}',
            severity='Info'
            )
        else:
            await interaction.followup.send(f"Hello <@{interaction.user.id}>. I could not find any pending approvals for <@&{allyRole.id}>. They may have already been approved. If you believe this is an error please contact admin.")
            logger.write_log(
            action='/approve_all',
            payload=f'User was not approved because a pending user was not found.',
            severity='Debug'
            )
    except Exception as e:
        logger.write_log(
            action=None,
            payload=str(e),
            severity='Error'
        )
        admin_user_id = gcp_secrets.get_secret_contents('discord-bot-admin-user-id')
        adminUser = interaction.guild.get_member(int(admin_user_id))
        await adminUser.send(f'An error occured in petebot; command /approve_all; {e}')
        # end deferral of user on error
        await interaction.followup.send(f"Hello <@{interaction.user.id}>. This command has failed. A notification has been sent to admin to investigate.")

'''
/APPROVE [player]
Approve an applicant
'''
@bot.tree.command(name="approve", description="Approve a pending member to the alliance")
@app_commands.describe(travianacct="The Travian username of an applicant")
@app_commands.choices(alliance=[
        app_commands.Choice(name="DLT", value="DLT"),
        app_commands.Choice(name="NONA", value="NONA"),
        app_commands.Choice(name="TFM", value="TFM"),
        app_commands.Choice(name="TCO", value="TCO"),
        app_commands.Choice(name="WP", value="WP")
        ])
async def approve(interaction: discord.Interaction, travianacct: str, alliance: app_commands.Choice[str]):
    logger.write_log(
    action='/approve',
    payload=f'User {interaction.user} invoked the /approve command for {travianacct} and role {alliance.value}.',
    severity='Debug'
    )
    # get leader / ally role and determine if users have permission to use command
    try:
        leaderRole = discord.utils.get(interaction.guild.roles, name='LEADER-'+str(alliance.value).upper())
        allyRole = discord.utils.get(interaction.guild.roles, name=str(alliance.value).upper())
    except Exception as e:
        logger.write_log(
            action=None,
            payload=str(e),
            severity='Error'
        )
        admin_user_id = gcp_secrets.get_secret_contents('discord-bot-admin-user-id')
        adminUser = interaction.guild.get_member(int(admin_user_id))
        await adminUser.send(f'An error occured in petebot; command /approve; {e}')
    # check if command caller has leader role
    if leaderRole.id not in [y.id for y in interaction.user.roles]:
        await interaction.response.send_message(f"Hello <@{interaction.user.id}>. You do not have permission to approve users for <@&{allyRole.id}>. If you believe this is an error please contact admin.")
        return

    # get user in firestore database and mark them as approved = true
    try:
        user = firestore.check_user(travianUsername=str(travianacct).lower(), guildId=interaction.guild_id)
        # if user exists in firestore
        if user:
            logger.write_log(
            action='/approve',
            payload=f'Found user with discordUsername: {user["discordUsername"]} and Travian UN: {user["travianUsername"]}.',
            severity='Debug'
            )
            # if user has the role you're approving
            if user['allianceRole'] == str(alliance.value).upper(): # if user 
                # update the user in Firestore
                approvedUser = firestore.approve_user(travianUsername=str(travianacct).lower(), guildId=interaction.guild_id)

                # grant role to user
                if approvedUser:
                    logger.write_log(
                    action='/approve',
                    payload=f'Found user with discordUsername: {user["discordUsername"]} and Travian UN: {user["travianUsername"]}. who has not been approved',
                    severity='Debug'
                    )
                    # get the user based on their ID. Grant the user that role
                    targetMember = interaction.guild.get_member(int(approvedUser['userId']))
                    await targetMember.add_roles(allyRole)
                    # update their nickname
                    await targetMember.edit(nick=f'[{allyRole}] {user["travianUsername"]}')

                    logger.write_log(
                    action='/approve',
                    payload=f'Approved user with discordUsername: {user["discordUsername"]} and Travian UN: {user["travianUsername"]} to alliance: {alliance.value}',
                    severity='Info'
                    )
                    await interaction.response.send_message(f"User **{travianacct}** has been approved to join alliance.")
                    return
            else:
                await interaction.response.send_message(f"The action was unsuccessful because user **{travianacct}** has applied to {user['allianceRole']}. They may have updated their request form before you submitted this command. No action has been taken.")
        else:
            await interaction.response.send_message(f"There are no pending approvals for **{travianacct}**. They may have already been approved. If you believe this is an error please contact admin.")
            logger.write_log(
            action='/approve',
            payload=f'User was not approved because a pending user was not found.',
            severity='Debug'
            )
    except Exception as e:
        logger.write_log(
            action=None,
            payload=str(e),
            severity='Error'
        )
        admin_user_id = gcp_secrets.get_secret_contents('discord-bot-admin-user-id')
        adminUser = interaction.guild.get_member(int(admin_user_id))
        await adminUser.send(f'An error occured in petebot; command /approve; {e}')

'''
/REJECT [player]
Reject an applicant
'''
@bot.tree.command(name="reject", description="Reject a pending member's request to join the alliance.")
@app_commands.describe(travianacct="The Travian username of an applicant")
@app_commands.choices(alliance=[
        app_commands.Choice(name="DLT", value="DLT"),
        app_commands.Choice(name="NONA", value="NONA"),
        app_commands.Choice(name="TFM", value="TFM"),
        app_commands.Choice(name="TCO", value="TCO"),
        app_commands.Choice(name="WP", value="WP")
        ])
async def reject(interaction: discord.Interaction, travianacct: str, alliance: app_commands.Choice[str]):
    logger.write_log(
    action='/reject',
    payload=f'User {interaction.user} invoked the /reject command for {travianacct}',
    severity='Debug'
    )
    # determine if user has permission to use command
    try:
        leaderRole = discord.utils.get(interaction.guild.roles, name='LEADER-'+str(alliance.value).upper())
        allyRole = discord.utils.get(interaction.guild.roles, name=str(alliance.value).upper())
    except Exception as e:
        logger.write_log(
            action=None,
            payload=str(e),
            severity='Error'
        )
        admin_user_id = gcp_secrets.get_secret_contents('discord-bot-admin-user-id')
        adminUser = interaction.guild.get_member(int(admin_user_id))
        await adminUser.send(f'An error occured in petebot; command /reject; {e}')
    # check if command caller has leader role
    if leaderRole.id not in [y.id for y in interaction.user.roles]:
        await interaction.response.send_message(f"Hello <@{interaction.user.id}>. You do not have permission to reject users for <@&{allyRole.id}>. If you believe this is an error please contact admin.")
        return

    # find user in firestore, mark them as rejected
    try:
        user = firestore.check_user(travianUsername=str(travianacct).lower(), guildId=interaction.guild_id)
        # if user exists in firestore
        if user:
            logger.write_log(
            action='/reject',
            payload=f'Found user with discordUsername: {user["discordUsername"]} and Travian UN: {user["travianUsername"]}.',
            severity='Debug'
            )
            # if user has the role you're approving
            if user['allianceRole'] == str(alliance.value).upper(): # if user 
                # update the user in Firestore
                rejectedUser = firestore.reject_user(travianUsername=str(travianacct).lower(), guildId=interaction.guild_id)
                if rejectedUser:
                    logger.write_log(
                    action='/reject',
                    payload=f'Found user with discordUsername: {user["discordUsername"]} and Travian UN: {user["travianUsername"]}. who has not been approved/rejected',
                    severity='Debug'
                    )
                    # get the user based on their ID. Grant the user that role
                    targetMember = interaction.guild.get_member(int(rejectedUser['userId']))
                    await targetMember.send(f'You have been rejected from joining {allyRole} by leadership. You have also been blocked from applying to other alliances. If you believe this is a mistake please contact leadership.\n*This is an automated message. Do not respond as it will not be read.*')
                    logger.write_log(
                    action='/reject',
                    payload=f'Rejected user with discordUsername: {user["discordUsername"]} and Travian UN: {user["travianUsername"]} to alliance: {alliance.value}',
                    severity='Info'
                    )
                    await interaction.response.send_message(f"User **{travianacct}** has been successfully rejected from joining the coalition. They are now blocked from joining any alliance. If this needs to be corrected please contact admin.")
                    return
            else:
                await interaction.response.send_message(f"The action was unsuccessful because user **{travianacct}** has applied to {user['allianceRole']}. They may have updated their request form before you submitted this command. No action has been taken.")
        else:
            await interaction.response.send_message(f"There are no pending approvals for **{travianacct}**. They may have already been approved. If you believe this is an error please contact admin.")
            logger.write_log(
            action='/reject',
            payload=f'User was not approved because a pending user was not found.',
            severity='Debug'
            )
    except Exception as e:
        logger.write_log(
            action=None,
            payload=str(e),
            severity='Error'
        )
        admin_user_id = gcp_secrets.get_secret_contents('discord-bot-admin-user-id')
        adminUser = interaction.guild.get_member(int(admin_user_id))
        await adminUser.send(f'An error occured in petebot; command /reject; {e}')

# SLASH COMMANDS
'''
/TRANSLATE
Given input text and target language, translate text from the google translation API
'''
@bot.tree.command(name="translate", description="Translate input text to a specific language. Replies with english / translated language.")
@app_commands.describe(text="Text to translate")
@app_commands.choices(target_language=[
        app_commands.Choice(name="Arabic", value="ar"),
        app_commands.Choice(name="Bosnian", value="bs"),
        app_commands.Choice(name="English", value="en"),
        app_commands.Choice(name="German", value="de"),
        app_commands.Choice(name="Finnish", value="fi"),
        app_commands.Choice(name="Italian", value="it"),
        app_commands.Choice(name="Portuguese", value="pt"),
        app_commands.Choice(name="Romanian", value="ro"),
        app_commands.Choice(name="Russian", value="ru"),
        app_commands.Choice(name="Serbian", value="sr"),
        app_commands.Choice(name="Spanish", value="es"),
        app_commands.Choice(name="Turkish", value="tr"),
        app_commands.Choice(name="Ukranian", value="uk")
        ])
async def translate(interaction: discord.Interaction, text: str, target_language: app_commands.Choice[str]):
    logger.write_log(
        action='/translate',
        payload=f'User {interaction.user.name} invoked the /translate command',
        severity='Debug'
    )
    # message can take longer than 3 second timeout. defer
    await interaction.response.defer()
 
    try:
        translateDict = gcp_translate.translate_text(text, target_language.value)
        '''
        Format:
        EN: [English text]
        TR: [Translated Language]
        '''
        # if detected language is english
        if translateDict['detectedSourceLanguageISO639'] == 'en':
            await interaction.followup.send(f"English: {text}\n{target_language.name}: {translateDict['translatedText']}")
        elif target_language.value == 'en':
            await interaction.followup.send(f"English: {translateDict['translatedText']}\n{translateDict['detectedSourceLanguage']}: {text}")
        else:
            await interaction.followup.send(f"{translateDict['detectedSourceLanguage']}: {text}\n{target_language.name}: {translateDict['translatedText']}")

    except Exception as e:
        logger.write_log(
            action='/translate',
            payload=str(e),
            severity='Error'
        )
        admin_user_id = gcp_secrets.get_secret_contents('discord-bot-admin-user-id')
        adminUser = interaction.guild.get_member(int(admin_user_id))
        await adminUser.send(f'An error occured in petebot; command /translate; {e}')
        await interaction.followup.send(f"Hello <@{interaction.user.id}>. This command has failed. A notification has been sent to admin to investigate.")    

'''
/TRANSLATETHIS
Given input text and target language, translate text from the google translation API
'''
@bot.tree.command(name="translate_this", description="Translate input text to a specific language. Send the translation in a private message.")
@app_commands.describe(text="Text to translate")
@app_commands.choices(target_language=[
        app_commands.Choice(name="Arabic", value="ar"),
        app_commands.Choice(name="Bosnian", value="bs"),
        app_commands.Choice(name="Croatian", value="hr"),
        app_commands.Choice(name="English", value="en"),
        app_commands.Choice(name="German", value="de"),
        app_commands.Choice(name="Finnish", value="fi"),
        app_commands.Choice(name="Italian", value="it"),
        app_commands.Choice(name="Japanese", value="ja"),
        app_commands.Choice(name="Korean", value="ko"),
        app_commands.Choice(name="Lithuanian", value="lt"),
        app_commands.Choice(name="Macedonian", value="mk"),
        app_commands.Choice(name="Polish", value="pl"),
        app_commands.Choice(name="Portuguese", value="pt"),
        app_commands.Choice(name="Romanian", value="ro"),
        app_commands.Choice(name="Russian", value="ru"),
        app_commands.Choice(name="Serbian", value="sr"),
        app_commands.Choice(name="Slovenian", value="sl"),
        app_commands.Choice(name="Spanish", value="es"),
        app_commands.Choice(name="Swedish", value="sv"),
        app_commands.Choice(name="Turkish", value="tr"),
        app_commands.Choice(name="Ukranian", value="uk")
        ])
async def translate_this(interaction: discord.Interaction, text: str, target_language: app_commands.Choice[str]):
    logger.write_log(
        action='/translate_this',
        payload=f'User {interaction.user.name} invoked the /translate command',
        severity='Debug'
    )
    # message can take longer than 3 second timeout. defer for 5 seconds
    await interaction.response.defer(ephemeral=True)
    # await asyncio.sleep(4) # Doing stuff

    try:
        translateDict = gcp_translate.translate_text(text, target_language.value)

        await interaction.followup.send(f"Detected Language: {translateDict['detectedSourceLanguage']}\n{target_language.name}: {translateDict['translatedText']}", ephemeral=True)

    except Exception as e:
        logger.write_log(
            action='/translate',
            payload=str(e),
            severity='Error'
        )
        admin_user_id = gcp_secrets.get_secret_contents('discord-bot-admin-user-id')
        adminUser = interaction.guild.get_member(int(admin_user_id))
        await adminUser.send(f'An error occured in petebot; command /translate_this; {e}')
        await interaction.followup.send(f"Hello <@{interaction.user.id}>. This command has failed. A notification has been sent to admin to investigate.", ephemeral=True)    


'''
/ADD_ROLE:
Ask user for emote/role. Create a new record for that association in Firestore
BUG: Currently using custom emoji's does not work. the interaction receives a weird format for the emoji <yup:serverid?> but the assign roles sees :yup:
'''
@bot.tree.command(name="add_role", description="Create a new role/emote combination for this channel")
@app_commands.describe(emote="Emote used to gain that role")
@app_commands.describe(role="Name of role in discord")
async def add_role(interaction: discord.Interaction, emote: str, role: str):
    logger.write_log(
        action='/add_role',
        payload=f'User {interaction.user.name} invoked the /add_role command',
        severity='Debug'
    )
    try:
        admin_user_id = gcp_secrets.get_secret_contents('discord-bot-admin-user-id')
        if interaction.user.id != int(admin_user_id):
            await interaction.response.send_message(f"{interaction.user.name}, you do not have permission to use this command.", ephemeral=True)
            logger.write_log(
                action='/add_role',
                payload=f'User {interaction.user.name} was blocked from using the /add_role command',
                severity='Debug'
            )
            return
        response = firestore.add_role(interaction.guild_id, emote, role) # attempts to add role. If response returns it was successful
        await interaction.response.send_message(f"Hello {interaction.user.name}, {response}")

    except Exception as e:
        logger.write_log(
            action='/add_role',
            payload=str(e),
            severity='Error'
        )


'''
/REMOVE_ROLE:
Ask user for emote/role. Remove the record for that association from Firestore.
If the association doesn't exist in Firestore let the user know.
'''

@bot.tree.command(name="remove_role", description="Remove role/emote combination for this channel")
@app_commands.describe(emote="Emote used to gain that role")
async def remove_role(interaction: discord.Interaction, emote: str):
    logger.write_log(
        action='/remove_role',
        payload=f'User {interaction.user.name} invoked the /remove_role command',
        severity='Debug'
    )
    try:
        admin_user_id = gcp_secrets.get_secret_contents('discord-bot-admin-user-id')
        if interaction.user.id != int(admin_user_id):
            await interaction.response.send_message(f"{interaction.user.name}, you do not have permission to use this command.", ephemeral=True)
            logger.write_log(
                action='/remove_role',
                payload=f'User {interaction.user.name} was blocked from using the /remove_role command',
                severity='Debug'
            )
            return
        response = firestore.remove_role(interaction.guild_id, emote)
        await interaction.response.send_message(f"Hello {interaction.user.name}, {response}")
    
    except Exception as e:
        logger.write_log(
            action='/remove_role',
            payload=str(e),
            severity='Error'
        )

'''
!SHOW_ROLES:
Show a user every single emote/role combination in firestore.
If there are no associations in Firestore let the user know.
'''
@bot.command()
async def show_roles(ctx):
    try:
        role_list = firestore.show_roles(ctx.message.guild.id)
        # if roles exist
        if role_list:
            response = ''
            for dict in role_list:
                #for i in dict:
                response += f'\n {dict["roleEmote"]} | #{dict["roleName"]}'
            response = f'The following emote/roles are set for this server:{response}'
        else:
            response = 'There are currently no emote/roles set for this server. Add one using /add_role.'
        await ctx.send(f"Hello {ctx.message.author}, {response}")
    
    except Exception as e:
        logger.write_log(
            action='!show_roles',
            payload=str(e),
            severity='Error'
        )


# EVENTS
@bot.event
async def on_raw_reaction_add(payload):
    '''
    give a role based on a reaction emoji
    '''

    # get the server_config for a channel from firestore. uses the guild_id from the incoming payload
    messageId = firestore.get_messageID(payload.guild_id)

    # create a guild object used for other things.
    guild = bot.get_guild(payload.guild_id)

    # do nothing if the reaction is on any message that isnt the role message defined in firestore
    if payload.message_id != messageId:
        return

    # look up the associated role in firestore based on the emote from the payload
    # do nothing if the reaction does not match a document in firestore
    firestoreRoleName = firestore.get_role(payload.guild_id, payload.emoji.name)
    if firestoreRoleName == None:
        logger.write_log(
            action='on_raw_reaction_add',
            payload=f"No Role configured for {payload.emoji.name}, taking no action.",
            severity='Debug'
        )
        return

    # assign user the roleName
    discordRoleName = discord.utils.get(guild.roles, name=firestoreRoleName)
    await payload.member.add_roles(discordRoleName)

    logger.write_log(
        action='on_raw_reaction_add',
        payload=f"User {payload.member} emoted {payload.emoji.name}. Adding role #{firestoreRoleName}.",
        severity='Info'
    )

@bot.event
async def on_raw_reaction_remove(payload):
    '''
    remove a role based on a reaction emoji removal
    '''

    # get the server_config for a channel from firestore. uses the guild_id from the incoming payload
    messageId = firestore.get_messageID(payload.guild_id)

    # create a guild object used for other things.
    guild = bot.get_guild(payload.guild_id)

    # do nothing if the reaction is on any message that isnt the role message defined in the config
    if payload.message_id != messageId:
        return

    # the remove_roles requires a memberid
    member_id = guild.get_member(payload.user_id)

    # get the member's name as well
    member = await guild.fetch_member(payload.user_id)

    # look up the associated role in firestore based on the emote from the payload
    # do nothing if the reaction does not match a document in firestore
    firestoreRoleName = firestore.get_role(payload.guild_id, payload.emoji.name)
    if firestoreRoleName == None:
        logger.write_log(
            action='on_raw_reaction_remove',
            payload=f'No Role configured for {payload.emoji.name}, taking no action.',
            severity='Debug'
        )
        return

    # assign user the roleName
    discordRoleName = discord.utils.get(guild.roles, name=firestoreRoleName)
    await member_id.remove_roles(discordRoleName)
    logger.write_log(
        action='on_raw_reaction_remove',
        payload=f'User {member} removed emote {payload.emoji.name}. Removing role #{firestoreRoleName}.',
        severity='Info'
    )

bot.run(token)