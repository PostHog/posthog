from django.db import models
from django.contrib.postgres.fields import JSONField


class DashboardItem(models.Model):
    dashboard: models.ForeignKey = models.ForeignKey(
        "Dashboard", related_name="items", on_delete=models.CASCADE, null=False
    )
    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    filters: JSONField = JSONField(default=dict)
    order: models.IntegerField = models.IntegerField(null=True, blank=True)
    type: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    deleted: models.BooleanField = models.BooleanField(default=False)
