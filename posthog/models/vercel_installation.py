from django.db import models

from posthog.models.utils import RootTeamMixin, UpdatedMetaFields, UUIDModel


class VercelInstallation(UpdatedMetaFields, UUIDModel, RootTeamMixin):
    """
    Each Vercel Team has at most one Vercel Installation.
    Only one Vercel Team is connected per PostHog Organization.
    """

    organization = models.OneToOneField("Organization", on_delete=models.CASCADE)
    installation_id = models.CharField(max_length=255, unique=True)
    billing_plan_id = models.CharField(max_length=255, null=True, blank=True)
    upsert_data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
