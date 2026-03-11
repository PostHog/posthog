import logging

from django.db import models

from posthog.models.team import Team
from posthog.models.team.extensions import register_team_extension_signal

logger = logging.getLogger(__name__)


class TeamSnippetConfig(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)

    # Version pin: null = use latest, "1.358.0" = exact, "v1" = major, "v1.358" = minor
    snippet_version_pin = models.CharField(max_length=50, null=True, blank=True, default=None)


register_team_extension_signal(TeamSnippetConfig, logger=logger)
