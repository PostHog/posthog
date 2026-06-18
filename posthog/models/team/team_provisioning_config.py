import logging

from django.db import models

from posthog.models.team.extensions import register_team_extension_signal

logger = logging.getLogger(__name__)


class TeamProvisioningConfig(models.Model):
    team = models.OneToOneField("posthog.Team", on_delete=models.CASCADE, primary_key=True)

    stripe_project_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    service_id = models.CharField(max_length=255, default="analytics")


register_team_extension_signal(TeamProvisioningConfig, logger=logger)
