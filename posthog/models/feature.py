from django.db import models
from django.utils import timezone


class Feature(models.Model):
    class StatusType(models.TextChoices):
        PRE_ALPHA = "pre_alpha", "Pre-alpha"
        ALPHA = "alpha", "Alpha"
        BETA = "beta", "Beta"
        GENERAL_AVAILABILITY = "general_availability", "GA"

    name = models.CharField(max_length=400, blank=True)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    description = models.TextField(blank=True)
    documentation_url = models.URLField(blank=True)
    issue_url = models.URLField(blank=True)
    status = models.CharField(max_length=32, choices=StatusType.choices, default="pre_alpha")
    primary_feature_flag = models.ForeignKey("FeatureFlag", on_delete=models.RESTRICT, blank=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    archived = models.BooleanField(default=False)
    deleted = models.BooleanField(default=False)
