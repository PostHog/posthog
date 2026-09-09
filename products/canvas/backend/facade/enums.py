from django.db import models


class SketchpadActorKind(models.TextChoices):
    USER = "user", "User"
    AGENT = "agent", "Agent"
<<<<<<< HEAD


class SketchpadRecordKind(models.TextChoices):
    FRAGMENT = "fragment", "Fragment"
    SOURCE = "source", "Source"
    COMPILED = "compiled", "Compiled"
    STATE = "state", "State"
=======
>>>>>>> 47aade59919 (feat(canvas): add sketchpad models and migration)
