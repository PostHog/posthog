from django.db import models

from posthog.models.team import Team
from posthog.models.utils import UUIDModel


class PropertyDefinition(UUIDModel):
    team: models.ForeignKey = models.ForeignKey(
        Team, on_delete=models.CASCADE, related_name="property_definitions", related_query_name="team",
    )
    name: models.CharField = models.CharField(max_length=400)
    is_numerical: models.BooleanField = models.BooleanField(
        default=False,
    )  # whether the property can be interpreted as a number, and therefore used for math aggregation operations
    query_usage_30_day: models.IntegerField = models.IntegerField(
        default=None, null=True,
    )  # Number of times the event has been used in a query in the last 30 rolling days (computed asynchronously)

    # DEPRECATED
    volume_30_day: models.IntegerField = models.IntegerField(
        default=None, null=True,
    )  # Deprecated in #4480

    class Meta:
        unique_together = ("team", "name")

    def __str__(self) -> str:
        return f"{self.name} / {self.team.name}"
