from django.db import models
from django.contrib.postgres.fields import JSONField
from django.utils import timezone

class FeatureFlag(models.Model):
    name: models.CharField = models.CharField(max_length=400)
    key: models.CharField = models.CharField(max_length=400)

    filters: JSONField = JSONField(default=dict)
    rollout_percentage: models.IntegerField = models.IntegerField(null=True, blank=True)

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    deleted: models.BooleanField = models.BooleanField(default=False)
    active: models.BooleanField = models.BooleanField(default=True)