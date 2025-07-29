from django.db import models

from posthog.models.utils import UpdatedMetaFields, UUIDModel


class VercelInstallation(UpdatedMetaFields, UUIDModel):
    organization = models.ForeignKey("Organization", on_delete=models.CASCADE)
    installation_id = models.CharField(max_length=255, unique=True)
    billing_plan_id = models.CharField(max_length=255, null=True, blank=True)
    upsert_data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
