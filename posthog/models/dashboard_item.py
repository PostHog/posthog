from django.contrib.postgres.fields import JSONField
from django.db import models


class DashboardItem(models.Model):
    dashboard: models.ForeignKey = models.ForeignKey(
        "Dashboard", related_name="items", on_delete=models.CASCADE, null=True, blank=True
    )
    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    filters: JSONField = JSONField(default=dict)
    order: models.IntegerField = models.IntegerField(null=True, blank=True)
    type: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    deleted: models.BooleanField = models.BooleanField(default=False)
    saved: models.BooleanField = models.BooleanField(default=False)
    created_at: models.DateTimeField = models.DateTimeField(null=True, blank=True, auto_now_add=True)
    layouts: JSONField = JSONField(default=dict)
    color: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    last_refresh: models.DateTimeField = models.DateTimeField(blank=True, null=True)
    refreshing: models.BooleanField = models.BooleanField(default=False)
    funnel: models.ForeignKey = models.ForeignKey("Funnel", on_delete=models.CASCADE, null=True, blank=True)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
