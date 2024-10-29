from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils import timezone

from posthog.models.team import Team
from posthog.models.utils import UUIDModel


class EventDefinition(UUIDModel):
    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name="event_definitions",
        related_query_name="team",
    )
    project = models.ForeignKey("Project", on_delete=models.CASCADE, null=True)
    name = models.CharField(max_length=400)
    created_at = models.DateTimeField(default=timezone.now, null=True)
    last_seen_at = models.DateTimeField(default=None, null=True)

    # DEPRECATED
    # Number of times the event has been used in a query in the last 30 rolling days (computed asynchronously every other blue moon)
    query_usage_30_day = models.IntegerField(default=None, null=True)

    # DEPRECATED
    # Volume of events in the last 30 rolling days (computed asynchronously)
    volume_30_day = models.IntegerField(default=None, null=True)

    class Meta:
        unique_together = ("team", "name")
        indexes = [
            GinIndex(
                name="index_event_definition_name",
                fields=["name"],
                opclasses=["gin_trgm_ops"],
            )  # To speed up DB-based fuzzy searching
        ]

    def __str__(self) -> str:
        return f"{self.name} / {self.team.name}"
