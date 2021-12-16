from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils import timezone

from posthog.models.team import Team


class EventProperty(models.Model):
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    event: models.CharField = models.CharField(max_length=400, null=False)
    property: models.CharField = models.CharField(max_length=400, null=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['team', 'event', 'property'], name='posthog_event_property_unique_team_event_property'),
        ]
        indexes = [
            # To speed up direct lookups
            models.Index(fields=["team", "event"]),
            models.Index(fields=["team", "property"]),
            # To speed up DB-based fuzzy searching
            GinIndex(name="index_event_property_event", fields=["event"], opclasses=["gin_trgm_ops"]),
            GinIndex(name="index_event_property_property", fields=["property"], opclasses=["gin_trgm_ops"]),
        ]

    def __str__(self) -> str:
        return f"{self.event} / {self.property} / {self.team.name}"
