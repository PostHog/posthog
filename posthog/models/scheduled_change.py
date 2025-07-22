from django.db import models
from posthog.models.utils import RootTeamMixin


class ScheduledChange(RootTeamMixin, models.Model):
    class AllowedModels(models.TextChoices):
        FEATURE_FLAG = "FeatureFlag", "feature flag"

    id = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")
    record_id = models.CharField(max_length=200)
    model_name = models.CharField(max_length=100, choices=AllowedModels.choices)
    payload = models.JSONField(default=dict)
    scheduled_at = models.DateTimeField()
    executed_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.CharField(max_length=400, null=True, blank=True)

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["scheduled_at", "executed_at"]),
        ]
