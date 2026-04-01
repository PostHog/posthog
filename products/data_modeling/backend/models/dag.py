from datetime import timedelta

from django.db import models

from posthog.models import Team
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class DAG(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    name = models.TextField(max_length=2048, db_index=True)
    description = models.TextField(blank=True, default="")
    sync_frequency_interval = models.DurationField(default=timedelta(days=1), null=True, blank=True)

    class Meta:
        db_table = "posthog_datamodelingdag"
        constraints = [
            models.UniqueConstraint(
                name="name_unique_within_team",
                fields=["team", "name"],
            ),
        ]
