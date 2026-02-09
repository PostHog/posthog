from django.db import models

from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class CustomerJourney(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    insight = models.ForeignKey("posthog.Insight", on_delete=models.CASCADE)
    name = models.CharField(max_length=400)
    description = models.TextField(null=True, blank=True)
    order = models.IntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=["team_id", "order"]),
        ]
