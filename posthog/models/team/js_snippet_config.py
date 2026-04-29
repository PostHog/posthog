import logging

from django.db import models

from posthog.models.team.extensions import register_team_extension_signal

logger = logging.getLogger(__name__)


class TeamJsSnippetConfig(models.Model):
    team = models.OneToOneField("posthog.Team", on_delete=models.CASCADE, primary_key=True)

    # Version pin: null = use latest, "1.358.0" = exact, "1" = major, "1.358" = minor
    js_snippet_version = models.CharField(max_length=50, null=True, blank=True, default=None)


register_team_extension_signal(TeamJsSnippetConfig, logger=logger)
