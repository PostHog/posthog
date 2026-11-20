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

    # Set when the project got its default sync failure alert, or already had a warehouse source
    # alert of its own at that time. Alerts are hard deleted, so this is what stops the default
    # coming back after a person deletes it.
    default_failure_alert_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "data_warehouse"
