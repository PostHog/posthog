from django.db import models

from posthog.models.team import Team


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
