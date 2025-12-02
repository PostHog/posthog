from django.db import models


class Channel(models.TextChoices):
    """Supported channels for conversations."""

    WIDGET = "widget", "Widget"
    EMAIL = "email", "Email"
    SLACK = "slack", "Slack"
