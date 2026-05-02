from django.db import models


class Channel(models.TextChoices):
    WIDGET = "widget", "Widget"
    EMAIL = "email", "Email"
    SLACK = "slack", "Slack"
    TEAMS = "teams", "Microsoft Teams"


class ChannelDetail(models.TextChoices):
    # Slack sub-types
    SLACK_CHANNEL_MESSAGE = "slack_channel_message", "Channel message"
    SLACK_BOT_MENTION = "slack_bot_mention", "Bot mention"
    SLACK_EMOJI_REACTION = "slack_emoji_reaction", "Emoji reaction"
    # Teams sub-types
    TEAMS_CHANNEL_MESSAGE = "teams_channel_message", "Teams channel message"
    TEAMS_BOT_MENTION = "teams_bot_mention", "Teams bot mention"
    # Widget sub-types
    WIDGET_EMBEDDED = "widget_embedded", "Widget"
    WIDGET_API = "widget_api", "API"


class Status(models.TextChoices):
    NEW = "new", "New"
    OPEN = "open", "Open"
    PENDING = "pending", "Pending"
    ON_HOLD = "on_hold", "On hold"
    RESOLVED = "resolved", "Resolved"


class Priority(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"


class RuleType(models.TextChoices):
    TONE = "tone", "Tone"
    ESCALATION = "escalation", "Escalation"
