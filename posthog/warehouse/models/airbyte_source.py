from posthog.models.utils import UUIDModel, CreatedMetaFields, sane_repr
from django.db import models
from posthog.models.team import Team


class AirbyteSource(CreatedMetaFields, UUIDModel):
    source_id: models.CharField = models.CharField(max_length=400)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)

    __repr__ = sane_repr("source_id")
