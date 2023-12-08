from django.db import models
from django.utils import timezone


class ScheduledChange(models.Model):
    class AllowedModels(models.TextChoices):
        FEATURE_FLAG = "FeatureFlag", "feature flag"

    class AllowedOperations(models.TextChoices):
        CHANGE_STATUS = "change_status", "change status"
        ADD_RELEASE_CONDITIONS = "add_release_conditions", "add release conditions"

    record_id = models.IntegerField()
    model_name: models.CharField = models.CharField(max_length=100, choices=AllowedModels.choices)
    operation: models.CharField = models.CharField(max_length=100, choices=AllowedOperations.choices)
    payload: models.JSONField = models.JSONField(default=dict)
    scheduled_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    executed_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    failure_reason = models.CharField(max_length=400, null=True, blank=True)

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.SET_NULL, null=True)
