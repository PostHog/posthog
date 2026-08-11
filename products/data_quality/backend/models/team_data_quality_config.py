import logging

from django.db import models

from posthog.models.team import Team
from posthog.models.team.extensions import register_team_extension_signal

logger = logging.getLogger(__name__)


class TeamDataQualityConfig(models.Model):
    """Per-team data quality settings, as a Team extension (posthog_team is never ALTERed).

    Warning behavior is unconditional -- checks always run and surface health. The gate only decides
    whether a blocking failure stops a materialization from publishing.
    """

    # db_constraint=False: a real FK constraint takes SHARE ROW EXCLUSIVE on posthog_team while
    # migrating, stalling writes under traffic.
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True, db_constraint=False)

    gate_materialization_on_checks = models.BooleanField(
        default=False,
        help_text="When true, a materialization whose error-severity checks fail is not published.",
    )

    class Meta:
        app_label = "data_quality"


register_team_extension_signal(TeamDataQualityConfig, logger=logger)
