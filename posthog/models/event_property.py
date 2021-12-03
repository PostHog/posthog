from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils import timezone

from posthog.models.team import Team


class EventProperty(models.Model):
    class PropertyType(models.TextChoices):
        NUMBER = "NUMBER", "Number"
        STRING = "STRING", "String"
        BOOLEAN = "BOOLEAN", "Boolean"
        DATETIME = "DATETIME", "DateTime"

    team: models.ForeignKey = models.ForeignKey(
        # "event_properties" is a field on Team, so have to call this "event_properties_model"
        Team,
        on_delete=models.CASCADE,
        related_name="event_properties_model",
        related_query_name="team",
    )
    event: models.CharField = models.CharField(max_length=400, null=False)
    property: models.CharField = models.CharField(max_length=400, null=False)

    # contains e.g. the date format
    property_type: models.CharField = models.CharField(
        max_length=20, choices=PropertyType.choices, default=PropertyType.STRING, null=True
    )
    property_type_format: models.CharField = models.CharField(max_length=100, null=True)

    # things we keep track of
    total_volume: models.IntegerField = models.IntegerField(default=None, null=True)
    created_at: models.DateTimeField = models.DateTimeField(default=timezone.now, null=True)
    last_seen_at: models.DateTimeField = models.DateTimeField(default=None, null=True)

    class Meta:
        unique_together = ("team", "event", "property")
        indexes = [
            # To speed up direct lookups
            models.Index(fields=["team", "event"]),
            models.Index(fields=["team", "property"]),
            models.Index(fields=["team", "total_volume"]),
            # To speed up DB-based fuzzy searching
            GinIndex(name="index_event_property_event", fields=["event"], opclasses=["gin_trgm_ops"]),
            GinIndex(name="index_event_property_property", fields=["property"], opclasses=["gin_trgm_ops"]),
        ]

    def __str__(self) -> str:
        return f"{self.event} / {self.property} / {self.team.name}"
