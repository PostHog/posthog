from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from django.db import models

from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

from products.data_modeling.backend.schedule import sync_frequency_interval_to_short_name

if TYPE_CHECKING:
    from posthog.models import Team

DEFAULT_DAG_NAME = "Default"


def build_cohort_dag_name(base_name: str, interval: timedelta) -> str:
    """Compose a cohort DAG name like 'Default (1h)' for a given base + frequency."""
    return f"{base_name} ({sync_frequency_interval_to_short_name(interval)})"


class DAG(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    team_id: int

    name = models.TextField(max_length=2048, db_index=True)
    description = models.TextField(blank=True, default="")
    source_control_path = models.TextField(
        blank=True, default="", help_text="Directory path in the source control repository for synced DAGs"
    )
    sync_frequency_interval = models.DurationField(default=timedelta(days=1), null=True, blank=True)

    @classmethod
    def get_or_create_default(cls, team: Team) -> DAG:
        dag, _ = cls.objects.get_or_create(team=team, name=DEFAULT_DAG_NAME)
        return dag

    @classmethod
    def get_or_create_for_frequency(cls, team: Team, interval: timedelta, *, base_name: str = DEFAULT_DAG_NAME) -> DAG:
        """Return the cohort DAG for `team` at `interval`, creating it if missing.

        Sets sync_frequency_interval on creation so downstream schedule-building
        code can read it directly from the DAG.
        """
        name = build_cohort_dag_name(base_name, interval)
        dag, _ = cls.objects.get_or_create(team=team, name=name, defaults={"sync_frequency_interval": interval})
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
