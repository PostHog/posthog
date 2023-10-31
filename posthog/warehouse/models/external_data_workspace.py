from posthog.models.utils import UUIDModel, CreatedMetaFields, sane_repr
from django.db import models
from posthog.models.team import Team


class ExternalDataWorkspace(CreatedMetaFields, UUIDModel):
    team: models.OneToOneField = models.OneToOneField(Team, on_delete=models.CASCADE)
    workspace_id: models.UUIDField = models.UUIDField()

    __repr__ = sane_repr("workspace_id")
