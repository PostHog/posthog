from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.utils import UUIDTModel


class HogFunctionUserTemplate(UUIDTModel):
    class Scope(models.TextChoices):
        ONLY_TEAM = "team", "Only team"
        ORGANIZATION = "organization", "Organization"

    name = models.CharField(max_length=400)
    description = models.TextField(blank=True, default="")
    icon_url = models.TextField(null=True, blank=True)
    tags = ArrayField(models.CharField(max_length=255), blank=True, default=list)
    scope = models.CharField(max_length=24, choices=Scope.choices, default=Scope.ONLY_TEAM)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    type = models.CharField(max_length=50)
    hog = models.TextField()
    inputs_schema = models.JSONField(default=list)
    inputs = models.JSONField(null=True, blank=True)
    filters = models.JSONField(null=True, blank=True)
    mappings = models.JSONField(null=True, blank=True)
    masking = models.JSONField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["team"]),
        ]

    def __str__(self):
        return f"HogFunctionUserTemplate {self.id}: {self.name}"
