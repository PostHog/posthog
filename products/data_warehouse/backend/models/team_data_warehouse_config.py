import logging

from django.db import models

from posthog.models.team import Team
from posthog.models.team.extensions import register_team_extension_signal

logger = logging.getLogger(__name__)


class TeamDataWarehouseConfig(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)

    # The dashboard embedded on the data ops "Dashboard" tab.
    # Null until the user visits the tab for the first time, at which point it is seeded.
    overview_dashboard = models.ForeignKey(
        "posthog.Dashboard",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="data_warehouse_config",
    )
    # Explicit annotation for Django's auto-generated FK id field (Pyright doesn't infer these).
    overview_dashboard_id: int | None

    class Meta:
        app_label = "data_warehouse"


register_team_extension_signal(TeamDataWarehouseConfig, logger=logger)
