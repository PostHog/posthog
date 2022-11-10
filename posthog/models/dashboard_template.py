from django.db import models

from posthog.models.utils import UUIDModel


class DashboardTemplate(UUIDModel):
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    name: models.CharField = models.CharField(max_length=400, null=True)
    source_dashboard: models.IntegerField = models.IntegerField(null=True)
    template: models.JSONField = models.JSONField(default=dict)
