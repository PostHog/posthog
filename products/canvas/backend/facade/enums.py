from django.db import models


class CanvasBoardActorKind(models.TextChoices):
    USER = "user", "User"
    AGENT = "agent", "Agent"
