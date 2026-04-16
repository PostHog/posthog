import logging

from django.db import models

from posthog.models.team import Team
from posthog.models.team.extensions import register_team_extension_signal

logger = logging.getLogger(__name__)


class TeamDataWarehouseConfig(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)

    # The dashboards embedded on the data ops "Dashboard" tab.
    # Seeded on first visit; supports multiple dashboards for future use.
    overview_dashboards = models.ManyToManyField(
        "dashboards.Dashboard",
        blank=True,
        related_name="+",
    )

    class Meta:
        app_label = "data_warehouse"


register_team_extension_signal(TeamDataWarehouseConfig, logger=logger)
