from django.db import models


class Channel(models.TextChoices):
    WIDGET = "widget", "Widget"
    EMAIL = "email", "Email"
    SLACK = "slack", "Slack"
    TEAMS = "teams", "Microsoft Teams"
    GITHUB = "github", "GitHub"


class MessageSource(models.TextChoices):
    """Where a single ticket message was written, which can differ from the ticket's channel:
    on a Slack ticket, a reply typed in the Slack thread is ``slack`` while one sent from the
    PostHog app is ``posthog``."""

    WIDGET = "widget", "Widget"
    EMAIL = "email", "Email"
    SLACK = "slack", "Slack"
    TEAMS = "teams", "Microsoft Teams"
    GITHUB = "github", "GitHub"
    ZENDESK = "zendesk", "Zendesk"
    POSTHOG = "posthog", "PostHog"


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
    # GitHub sub-types
    GITHUB_ISSUE = "github_issue", "GitHub issue"


class TicketStatus(models.TextChoices):
    NEW = "new", "New"
    OPEN = "open", "Open"
    PENDING = "pending", "Pending"
    ON_HOLD = "on_hold", "On hold"
    RESOLVED = "resolved", "Resolved"


# The class name feeds the derived OpenAPI component name TicketStatusEnum.
# Status is an alias for the many callers that import the short name.
Status = TicketStatus


class Priority(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    CRITICAL = "critical", "Critical"


class OrganizationIdSource(models.TextChoices):
    PERSON = "person", "Requester identity"
    SLACK_CHANNEL_ACCOUNT = "slack_channel_account", "Slack channel account"


class RuleType(models.TextChoices):
    TONE = "tone", "Tone"
    ESCALATION = "escalation", "Escalation"
