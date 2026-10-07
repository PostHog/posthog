from django.db import models

from posthog.models.scoping.manager import EnvironmentScopedManager


class TeamHomeTabDashboardConfig(models.Model):
    """Per-team choice of which dashboard the product analytics Home tab shows. Lives on a Team
    extension so posthog_team is never ALTERed."""

    # db_constraint=False: a real FK constraint takes SHARE ROW EXCLUSIVE on posthog_team while
    # migrating, stalling writes under traffic. String reference avoids importing Team at module
    # load time, which would circularly re-enter posthog.models.team (see dashboard_templates.py).
    team = models.OneToOneField(
        "posthog.Team", on_delete=models.CASCADE, primary_key=True, db_constraint=False, related_name="+"
    )

    dashboard = models.ForeignKey(
        "dashboards.Dashboard",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Dashboard shown on the product analytics Home tab. Null shows the built-in generic view.",
    )

    objects = EnvironmentScopedManager()

    class Meta:
        app_label = "dashboards"
