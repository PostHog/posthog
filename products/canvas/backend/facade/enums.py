from django.db import models


class SketchpadActorKind(models.TextChoices):
    USER = "user", "User"
    AGENT = "agent", "Agent"


class SketchpadRecordKind(models.TextChoices):
    FRAGMENT = "fragment", "Fragment"
    SOURCE = "source", "Source"
    COMPILED = "compiled", "Compiled"
    STATE = "state", "State"
