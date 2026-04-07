from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from django.db import models

from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

if TYPE_CHECKING:
    from posthog.models import Team

DEFAULT_DAG_NAME = "Default"


class DAG(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    name = models.TextField(max_length=2048, db_index=True)
    description = models.TextField(blank=True, default="")
    sync_frequency_interval = models.DurationField(default=timedelta(days=1), null=True, blank=True)

    @classmethod
    def get_or_create_default(cls, team: Team) -> DAG:
        dag, _ = cls.objects.get_or_create(team=team, name=DEFAULT_DAG_NAME)
        return dag

    @property
    def is_default(self) -> bool:
        return self.name == DEFAULT_DAG_NAME

    class Meta:
        db_table = "posthog_datamodelingdag"
        constraints = [
            models.UniqueConstraint(
                name="name_unique_within_team",
                fields=["team", "name"],
            ),
        ]
