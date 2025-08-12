from django.db import models

from posthog.models.team.team import Team
from ee.models.vercel.vercel_installation import VercelInstallation
from posthog.models.utils import UpdatedMetaFields, UUIDModel


class VercelResource(UpdatedMetaFields, UUIDModel):
    """
    Each Vercel Resource is connected to only one PostHog Project/Team.
    It also belongs to only one Vercel Installation.
    """

    team = models.OneToOneField(Team, on_delete=models.CASCADE)
    installation = models.ForeignKey(VercelInstallation, related_name="resources", on_delete=models.CASCADE)
    config = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
