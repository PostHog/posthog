from django.db import models
from django.utils import timezone

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class DashboardGroup(TeamScopedRootMixin, UUIDModel):
    dashboard = models.ForeignKey("dashboards.Dashboard", on_delete=models.CASCADE, related_name="groups")
    name = models.CharField(max_length=400)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    last_modified_at = models.DateTimeField(default=timezone.now)
    last_modified_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="modified_dashboard_groups",
        db_constraint=False,
    )
    # Real FK to posthog_team would take SHARE ROW EXCLUSIVE on a hot table during migrate.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)

    all_teams = models.Manager()  # noqa: DJ012

    class Meta(TeamScopedRootMixin.Meta):
        db_table = "posthog_dashboardgroup"
        default_manager_name = "all_teams"
