import os, json, asyncio, random, time
from datetime import timedelta
import discord
from discord import app_commands

BOT_NAME = "R.O.T.I"
FILE = "data.json"

def load():
    try:
        with open(FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

data = load()
for k in ("tickets", "users", "warns"):
    data.setdefault(k, {})

def save():
    with open(FILE, "w") as f:
        json.dump(data, f)

def udata(gid, uid):
    return data["users"].setdefault(
        f"{gid}:{uid}", {"xp": 0, "level": 0, "coins": 0, "last_daily": 0, "last_msg": 0})

def need(level):
    return 100 + 50 * level

# ---------------- TICKETS ----------------
class CloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.red,
                       emoji="🔒", custom_id="roti:close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        ch = interaction.channel
        topic = ch.topic or ""
        if not topic.startswith("ticket:"):
            return await interaction.response.send_message("Not a ticket.", ephemeral=True)
        owner_id = int(topic.split(":")[1])
        cfg = data["tickets"].get(str(interaction.guild_id), {})
        support = interaction.guild.get_role(cfg.get("role", 0))
        if not (interaction.user.id == owner_id
                or (support and support in interaction.user.roles)
                or interaction.user.guild_permissions.manage_channels):
            return await interaction.response.send_message("You can't close this.", ephemeral=True)
        await interaction.response.send_message("🔒 Closing in 5 seconds...")
        await asyncio.sleep(5)
        await ch.delete()

class OpenView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.green,
                       emoji="🎫", custom_id="roti:open")
    async def open(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild, member = interaction.guild, interaction.user
        cfg = data["tickets"].get(str(guild.id))
        if not cfg:
            return await interaction.response.send_message("Ticket system isn't set up.", ephemeral=True)
        for ch in guild.text_channels:
            if ch.topic == f"ticket:{member.id}":
                return await interaction.response.send_message(
                    f"You already have a ticket: {ch.mention}", ephemeral=True)
        category = guild.get_channel(cfg["category"])
        support = guild.get_role(cfg["role"])
        ow = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if support:
            ow[support] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        channel = await guild.create_text_channel(
            f"ticket-{member.name}", category=category, overwrites=ow, topic=f"ticket:{member.id}")
        embed = discord.Embed(title="🎫 Ticket opened",
                              description="Describe your issue and support will be with you soon.",
                              color=discord.Color.green())
        await channel.send(f"{member.mention} {support.mention if support else ''}",
                           embed=embed, view=CloseView())
        await interaction.response.send_message(f"Ticket created: {channel.mention}", ephemeral=True)

# ---------------- BOT ----------------
class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.add_view(OpenView())
        self.add_view(CloseView())
        await self.tree.sync()

client = Bot()
tree = client.tree

@tree.error
async def on_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        msg = f"⏳ Slow down! Try again in {error.retry_after:.0f}s."
    elif isinstance(error, app_commands.MissingPermissions):
        msg = "❌ You don't have permission for that."
    else:
        msg = "⚠️ Something went wrong."
        print(error)
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)

# ---------------- LEVELING ----------------
@client.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    u = udata(message.guild.id, message.author.id)
    now = time.time()
    if now - u["last_msg"] < 60:
        return
    u["last_msg"] = now
    u["xp"] += random.randint(15, 25)
    leveled = False
    while u["xp"] >= need(u["level"]):
        u["xp"] -= need(u["level"])
        u["level"] += 1
        u["coins"] += 50
        leveled = True
    save()
    if leveled:
        await message.channel.send(
            f"🎉 {message.author.mention} reached **level {u['level']}**! (+50 coins)")

@tree.command(name="rank", description="Show your level and XP")
async def rank(interaction: discord.Interaction, member: discord.Member = None):
    m = member or interaction.user
    u = udata(interaction.guild_id, m.id)
    e = discord.Embed(title=f"{m.display_name}'s rank", color=discord.Color.blurple())
    e.add_field(name="Level", value=u["level"])
    e.add_field(name="XP", value=f"{u['xp']}/{need(u['level'])}")
    await interaction.response.send_message(embed=e)

@tree.command(name="leaderboard", description="Top members by level or coins")
@app_commands.choices(kind=[app_commands.Choice(name="Levels", value="level"),
                            app_commands.Choice(name="Coins", value="coins")])
async def leaderboard(interaction: discord.Interaction, kind: app_commands.Choice[str]):
    prefix = f"{interaction.guild_id}:"
    rows = [(k.split(":")[1], v) for k, v in data["users"].items() if k.startswith(prefix)]
    key = kind.value
    rows.sort(key=lambda r: (r[1]["level"], r[1]["xp"]) if key == "level" else r[1]["coins"], reverse=True)
    lines = []
    for i, (uid, v) in enumerate(rows[:10], 1):
        val = f"Lv {v['level']}" if key == "level" else f"{v['coins']} 🪙"
        lines.append(f"**{i}.** <@{uid}> — {val}")
    await interaction.response.send_message(
        embed=discord.Embed(title=f"🏆 Top {kind.name}", description="\n".join(lines) or "No data yet.",
                            color=discord.Color.gold()))

# ---------------- ECONOMY (OwO style) ----------------
@tree.command(name="balance", description="Check your coins")
async def balance(interaction: discord.Interaction, member: discord.Member = None):
    m = member or interaction.user
    await interaction.response.send_message(f"🪙 {m.display_name} has **{udata(interaction.guild_id, m.id)['coins']}** coins.")

@tree.command(name="daily", description="Claim your daily coins")
async def daily(interaction: discord.Interaction):
    u = udata(interaction.guild_id, interaction.user.id)
    now = time.time()
    if now - u["last_daily"] < 86400:
        left = int(86400 - (now - u["last_daily"]))
        return await interaction.response.send_message(
            f"⏳ Come back in {left // 3600}h {(left % 3600) // 60}m.", ephemeral=True)
    amt = random.randint(100, 250)
    u["coins"] += amt
    u["last_daily"] = now
    save()
    await interaction.response.send_message(f"🎁 You claimed **{amt}** coins!")

ANIMALS = [("🐛", 5), ("🐰", 10), ("🦊", 20), ("🐺", 35), ("🦁", 60), ("🐉", 150)]

@tree.command(name="hunt", description="Hunt for animals and sell them")
@app_commands.checks.cooldown(1, 15)
async def hunt(interaction: discord.Interaction):
    found = random.choices(ANIMALS, weights=[40, 25, 15, 10, 7, 3], k=3)
    total = sum(v for _, v in found)
    u = udata(interaction.guild_id, interaction.user.id)
    u["coins"] += total
    save()
    await interaction.response.send_message(
        f"🏹 {interaction.user.mention} hunted {' '.join(a for a, _ in found)} and earned **{total}** coins!")

@tree.command(name="coinflip", description="Bet coins on a coin flip")
@app_commands.choices(side=[app_commands.Choice(name="Heads", value="heads"),
                            app_commands.Choice(name="Tails", value="tails")])
@app_commands.checks.cooldown(1, 5)
async def coinflip(interaction: discord.Interaction, amount: app_commands.Range[int, 1], side: app_commands.Choice[str]):
    u = udata(interaction.guild_id, interaction.user.id)
    if amount > u["coins"]:
        return await interaction.response.send_message("You don't have enough coins.", ephemeral=True)
    result = random.choice(["heads", "tails"])
    if result == side.value:
        u["coins"] += amount
        text = f"🪙 It's **{result}**! You won **{amount}** coins."
    else:
        u["coins"] -= amount
        text = f"🪙 It's **{result}**. You lost **{amount}** coins."
    save()
    await interaction.response.send_message(text)

@tree.command(name="give", description="Give coins to someone")
async def give(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1]):
    if member.bot or member.id == interaction.user.id:
        return await interaction.response.send_message("Pick someone else.", ephemeral=True)
    a = udata(interaction.guild_id, interaction.user.id)
    if amount > a["coins"]:
        return await interaction.response.send_message("You don't have enough coins.", ephemeral=True)
    a["coins"] -= amount
    udata(interaction.guild_id, member.id)["coins"] += amount
    save()
    await interaction.response.send_message(f"💸 Gave **{amount}** coins to {member.mention}.")

# ---------------- FUN ----------------
@tree.command(name="ping", description="Check bot latency")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Pong! {round(client.latency * 1000)}ms")

@tree.command(name="roll", description="Roll a dice")
async def roll(interaction: discord.Interaction, sides: app_commands.Range[int, 2, 1000] = 6):
    await interaction.response.send_message(f"🎲 You rolled **{random.randint(1, sides)}**")

@tree.command(name="8ball", description="Ask the magic 8ball")
async def eightball(interaction: discord.Interaction, question: str):
    a = ["Yes!", "No.", "Maybe...", "Definitely.", "Ask again later.", "Very doubtful.", "Without a doubt."]
    await interaction.response.send_message(f"🎱 **{question}**\n{random.choice(a)}")

@tree.command(name="hug", description="Hug someone")
async def hug(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.send_message(f"🤗 {interaction.user.mention} hugs {member.mention}!")

@tree.command(name="avatar", description="Show someone's avatar")
async def avatar(interaction: discord.Interaction, member: discord.Member = None):
    m = member or interaction.user
    await interaction.response.send_message(m.display_avatar.url)

# ---------------- MODERATION ----------------
@tree.command(name="kick", description="Kick a member")
@app_commands.default_permissions(kick_members=True)
@app_commands.checks.has_permissions(kick_members=True)
@app_commands.guild_only()
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"):
    try:
        await member.kick(reason=reason)
        await interaction.response.send_message(f"👢 Kicked {member} — {reason}")
    except discord.Forbidden:
        await interaction.response.send_message("I can't kick that member (check role order).", ephemeral=True)

@tree.command(name="ban", description="Ban a member")
@app_commands.default_permissions(ban_members=True)
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.guild_only()
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"):
    try:
        await member.ban(reason=reason)
        await interaction.response.send_message(f"🔨 Banned {member} — {reason}")
    except discord.Forbidden:
        await interaction.response.send_message("I can't ban that member (check role order).", ephemeral=True)

@tree.command(name="timeout", description="Timeout a member")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.guild_only()
async def timeout(interaction: discord.Interaction, member: discord.Member,
                  minutes: app_commands.Range[int, 1, 40320], reason: str = "No reason"):
    try:
        await member.timeout(timedelta(minutes=minutes), reason=reason)
        await interaction.response.send_message(f"🔇 Timed out {member} for {minutes}m — {reason}")
    except discord.Forbidden:
        await interaction.response.send_message("I can't timeout that member.", ephemeral=True)

@tree.command(name="untimeout", description="Remove a timeout")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.guild_only()
async def untimeout(interaction: discord.Interaction, member: discord.Member):
    await member.timeout(None)
    await interaction.response.send_message(f"🔊 Removed timeout from {member}.")

@tree.command(name="purge", description="Delete recent messages")
@app_commands.default_permissions(manage_messages=True)
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.guild_only()
async def purge(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"🧹 Deleted {len(deleted)} messages.", ephemeral=True)

@tree.command(name="warn", description="Warn a member")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.guild_only()
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str):
    key = f"{interaction.guild_id}:{member.id}"
    data["warns"].setdefault(key, []).append(reason)
    save()
    await interaction.response.send_message(
        f"⚠️ Warned {member.mention} — {reason} (total: {len(data['warns'][key])})")

@tree.command(name="warnings", description="View a member's warnings")
@app_commands.default_permissions(moderate_members=True)
@app_commands.guild_only()
async def warnings(interaction: discord.Interaction, member: discord.Member):
    w = data["warns"].get(f"{interaction.guild_id}:{member.id}", [])
    text = "\n".join(f"{i}. {r}" for i, r in enumerate(w, 1)) or "No warnings."
    await interaction.response.send_message(f"**{member}**\n{text}", ephemeral=True)

# ---------------- TICKET COMMANDS ----------------
@tree.command(name="ticket_setup", description="Post the ticket panel")
@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
async def ticket_setup(interaction: discord.Interaction, channel: discord.TextChannel,
                       category: discord.CategoryChannel, support_role: discord.Role):
    data["tickets"][str(interaction.guild_id)] = {"category": category.id, "role": support_role.id}
    save()
    embed = discord.Embed(title=f"{BOT_NAME} Support",
                          description="Click the button below to open a ticket.",
                          color=discord.Color.blurple())
    await channel.send(embed=embed, view=OpenView())
    await interaction.response.send_message("✅ Panel posted.", ephemeral=True)

@tree.command(name="add", description="Add a user to this ticket")
@app_commands.default_permissions(manage_channels=True)
@app_commands.guild_only()
async def add(interaction: discord.Interaction, user: discord.Member):
    if not (interaction.channel.topic or "").startswith("ticket:"):
        return await interaction.response.send_message("Use this inside a ticket.", ephemeral=True)
    await interaction.channel.set_permissions(user, view_channel=True, send_messages=True)
    await interaction.response.send_message(f"Added {user.mention}.")

@tree.command(name="remove", description="Remove a user from this ticket")
@app_commands.default_permissions(manage_channels=True)
@app_commands.guild_only()
async def remove(interaction: discord.Interaction, user: discord.Member):
    if not (interaction.channel.topic or "").startswith("ticket:"):
        return await interaction.response.send_message("Use this inside a ticket.", ephemeral=True)
    await interaction.channel.set_permissions(user, overwrite=None)
    await interaction.response.send_message(f"Removed {user.mention}.")

# ---------------- HELP ----------------
@tree.command(name="help", description="Show all commands")
async def help_cmd(interaction: discord.Interaction):
    e = discord.Embed(title=f"{BOT_NAME} Help", description="All commands use `/`",
                      color=discord.Color.blurple())
    e.add_field(name="📈 Levels", value="`/rank` `/leaderboard`", inline=False)
    e.add_field(name="🪙 Economy", value="`/balance` `/daily` `/hunt` `/coinflip` `/give`", inline=False)
    e.add_field(name="🎮 Fun", value="`/ping` `/roll` `/8ball` `/hug` `/avatar`", inline=False)
    e.add_field(name="🛡️ Moderation", value="`/kick` `/ban` `/timeout` `/untimeout` `/purge` `/warn` `/warnings`", inline=False)
    e.add_field(name="🎫 Tickets", value="`/ticket_setup` `/add` `/remove`", inline=False)
    await interaction.response.send_message(embed=e)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")

client.run(os.environ["DISCORD_TOKEN"])
