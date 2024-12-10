from django.db import models
from django.utils import timezone


class Feature(models.Model):
    name = models.CharField(max_length=400, blank=False)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    description = models.TextField(default="")
    documentation_url = models.URLField(blank=True)
    issue_url = models.URLField(blank=True)
    primary_early_access_feature = models.ForeignKey("EarlyAccessFeature", on_delete=models.RESTRICT, blank=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    archived = models.BooleanField(default=False)
    deleted = models.BooleanField(default=False)
