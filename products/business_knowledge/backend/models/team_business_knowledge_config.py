import logging

from django.db import models

from posthog.models.team import Team
from posthog.models.team.extensions import register_team_extension_signal

logger = logging.getLogger(__name__)


class TeamBusinessKnowledgeConfig(models.Model):
    """Per-team Business knowledge settings. Lives on a Team extension so posthog_team is never ALTERed."""

    # db_constraint=False: a real FK constraint takes SHARE ROW EXCLUSIVE on posthog_team while
    # migrating, stalling writes under traffic.
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True, db_constraint=False, related_name="+")

    learn_from_support_enabled = models.BooleanField(
        default=False,
        db_default=False,
        help_text=(
            "When true, PostHog learns reusable knowledge from public human replies on resolved "
            "support tickets. Requires Support to be enabled for this environment."
        ),
    )

    class Meta:
        app_label = "business_knowledge"


register_team_extension_signal(TeamBusinessKnowledgeConfig, logger=logger)
