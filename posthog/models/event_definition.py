import os

from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils import timezone

from posthog.models.team import Team
from posthog.models.utils import UUIDModel


class EventDefinition(UUIDModel):
    team: models.ForeignKey = models.ForeignKey(
        Team, on_delete=models.CASCADE, related_name="event_definitions", related_query_name="team",
    )
    name: models.CharField = models.CharField(max_length=400)
    created_at: models.DateTimeField = models.DateTimeField(default=timezone.now, null=True)
    last_seen_at: models.DateTimeField = models.DateTimeField(default=None, null=True)
    volume_30_day: models.IntegerField = models.IntegerField(
        default=None, null=True,
    )  # Volume of events in the last 30 rolling days (computed asynchronously)
    query_usage_30_day: models.IntegerField = models.IntegerField(
        default=None, null=True,
    )  # Number of times the event has been used in a query in the last 30 rolling days (computed asynchronously)

    class Meta:
        unique_together = ("team", "name")
        indexes = (
            [
                GinIndex(
                    name="index_event_definition_name", fields=["name"], opclasses=["gin_trgm_ops"]
                ),  # To speed up DB-based fuzzy searching
            ]
            if not os.environ.get("SKIP_TRIGRAM_INDEX_FOR_TESTS")
            else []
        )  # This index breaks the --no-migrations option when running tests

    def __str__(self) -> str:
        return f"{self.name} / {self.team.name}"
