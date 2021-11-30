from django.db import models
from django.utils import timezone


class Experiment(models.Model):
    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    description: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    filters: models.JSONField = models.JSONField(default=dict)
    feature_flags: models.ManyToManyField = models.ManyToManyField("FeatureFlag", blank=False)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
