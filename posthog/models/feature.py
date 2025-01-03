from django.db import models

from posthog.models.utils import UUIDModel, CreatedMetaFields


class Feature(CreatedMetaFields, UUIDModel):
    # Key must be unique per team across all features and all feature flags,
    # as the early access feature will create a flag with this same key.
    key = models.CharField(max_length=400, blank=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    name = models.CharField(max_length=400, blank=False)
    description = models.TextField(default="", blank=True)
    primary_early_access_feature = models.ForeignKey(
        "posthog.EarlyAccessFeature", on_delete=models.RESTRICT, blank=False
    )
    alerts = models.ManyToManyField("posthog.AlertConfiguration", through="posthog.FeatureAlertConfiguration")
    archived = models.BooleanField(default=False)
    deleted = models.BooleanField(default=False)


class FeatureAlertConfiguration(UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    feature = models.ForeignKey("posthog.Feature", on_delete=models.CASCADE)
    alert_configuration = models.ForeignKey("posthog.AlertConfiguration", on_delete=models.CASCADE)
    feature_insight_type = models.CharField(
        max_length=32,
        choices=[("success_metric", "Success Metric"), ("faiure_metric", "Failure Metric")],
    )
