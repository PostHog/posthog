from django.db import models

from posthog.models.vercel_installation import VercelInstallation
from posthog.models.utils import UpdatedMetaFields, UUIDModel


class VercelResource(UpdatedMetaFields, UUIDModel):
    installation = models.ForeignKey(VercelInstallation, related_name="resources", on_delete=models.CASCADE)
    resource_id = models.CharField(max_length=255, unique=True)
    config = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
