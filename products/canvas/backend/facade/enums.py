from django.db import models


class SketchpadActorKind(models.TextChoices):
    USER = "user", "User"
    AGENT = "agent", "Agent"
