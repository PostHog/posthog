from django.db import models

from posthog.models.utils import UUIDModel, CreatedMetaFields


class Feature(CreatedMetaFields, UUIDModel):
    name = models.CharField(max_length=400, blank=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    description = models.TextField(default="")
    documentation_url = models.URLField(blank=True)
    issue_url = models.URLField(blank=True)
    primary_early_access_feature = models.ForeignKey("EarlyAccessFeature", on_delete=models.RESTRICT, blank=False)
    alerts = models.ManyToManyField("posthog.AlertConfiguration", through="posthog.FeatureAlertConfiguration")
    archived = models.BooleanField(default=False)
    deleted = models.BooleanField(default=False)


class FeatureAlertConfiguration(models.Model):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    feature = models.ForeignKey("posthog.Feature", on_delete=models.CASCADE)
    alert_configuration = models.ForeignKey("posthog.AlertConfiguration", on_delete=models.CASCADE)
    feature_insight_type = models.CharField(
        max_length=32,
        choices=[("success_metric", "Success Metric"), ("faiure_metric", "Failure Metric")],
    )
