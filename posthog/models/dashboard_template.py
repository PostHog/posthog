from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.utils import UUIDModel


class DashboardTemplate(UUIDModel):
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    template_name: models.CharField = models.CharField(max_length=400, null=True)
    source_dashboard: models.IntegerField = models.IntegerField(null=True)
    dashboard_name: models.CharField = models.CharField(max_length=400, null=True)
    dashboard_description: models.CharField = models.CharField(max_length=400, null=True)
    dashboard_filters: models.JSONField = models.JSONField(null=True)
    tiles: models.JSONField = models.JSONField(default=list)
    tags: ArrayField = ArrayField(models.CharField(max_length=255), default=list)
