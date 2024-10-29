from django.db import models

from posthog.models.team import Team
from posthog.models.utils import sane_repr


class EventProperty(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    project = models.ForeignKey("Project", on_delete=models.CASCADE, null=True)
    event = models.CharField(max_length=400, null=False)
    property = models.CharField(max_length=400, null=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "event", "property"],
                name="posthog_event_property_unique_team_event_property",
            )
        ]
        indexes = [
            models.Index(fields=["team", "event"]),
            models.Index(fields=["team", "property"]),
        ]

    __repr__ = sane_repr("event", "property", "team_id")
