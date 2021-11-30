from django.contrib.postgres.indexes import GinIndex
from django.db import models

from posthog.models.team import Team
from posthog.models.utils import UUIDModel


class EventDefinition(UUIDModel):
    team: models.ForeignKey = models.ForeignKey(
        Team, on_delete=models.CASCADE, related_name="event_definitions", related_query_name="team",
    )
    name: models.CharField = models.CharField(max_length=400)
    volume_30_day: models.IntegerField = models.IntegerField(
        default=None, null=True,
    )  # Volume of events in the last 30 rolling days (computed asynchronously)
    query_usage_30_day: models.IntegerField = models.IntegerField(
        default=None, null=True,
    )  # Number of times the event has been used in a query in the last 30 rolling days (computed asynchronously)

    class Meta:
        unique_together = ("team", "name")
        indexes = [
            GinIndex(name="index_event_definition_name", fields=["name"], opclasses=["gin_trgm_ops"]),
        ]  # To speed up DB-based fuzzy searching

    def __str__(self) -> str:
        return f"{self.name} / {self.team.name}"
