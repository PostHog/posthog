from django.db import models


class Channel(models.TextChoices):
    WIDGET = "widget", "Widget"
    EMAIL = "email", "Email"
    SLACK = "slack", "Slack"


class Status(models.TextChoices):
    NEW = "new", "New"
    OPEN = "open", "Open"
    PENDING = "pending", "Pending"
    ON_HOLD = "on_hold", "On hold"
    RESOLVED = "resolved", "Resolved"


class RuleType(models.TextChoices):
    TONE = "tone", "Tone"
    ESCALATION = "escalation", "Escalation"
