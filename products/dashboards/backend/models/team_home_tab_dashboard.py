from django.db import models


class TeamHomeTabDashboard(models.Model):
    """The dashboard shown on the product analytics Home tab, separate from Team.primary_dashboard."""

    # String references avoid a circular import: this module loads at django.setup() via
    # products/dashboards/backend/models/__init__.py, which posthog.helpers.dashboard_templates
    # (in turn imported by posthog.models.team.team) pulls in before Team finishes defining itself.
    team = models.OneToOneField("posthog.Team", on_delete=models.CASCADE, primary_key=True)
    dashboard = models.ForeignKey(
        "dashboards.Dashboard", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
