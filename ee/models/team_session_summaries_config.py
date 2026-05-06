import logging

from django.db import models

from posthog.models.team import Team
from posthog.models.team.extensions import register_team_extension_signal

logger = logging.getLogger(__name__)


PRODUCT_CONTEXT_MAX_LENGTH = 10_000


class TeamSessionSummariesConfig(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)

    product_context = models.TextField(
        blank=True,
        default="",
        max_length=PRODUCT_CONTEXT_MAX_LENGTH,
        help_text=(
            "Free-form description of the team's product, used to tailor AI-generated session summaries. "
            "Injected into the system prompt of every summary generated for this team."
        ),
    )


register_team_extension_signal(TeamSessionSummariesConfig, logger=logger)
