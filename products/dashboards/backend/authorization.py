from collections.abc import Collection

from posthog.user_permissions import UserPermissions

from products.access_control.backend.facade.user_access_control import AccessControlLevelResource, UserAccessControl
from products.dashboards.backend.facade.authorization_contracts import AuthorizationDashboard
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile


class LegacyDashboardAuthorization:
    def __init__(self, access: UserAccessControl) -> None:
        if access.team is None:
            raise ValueError("Dashboard authorization requires a project")
        self.access = access
        self.team = access.team
        self.permissions = UserPermissions(access.user, self.team)
        self.dashboards: dict[str, Dashboard | None] = {}

    def _check(self, dashboard: Dashboard, level: AccessControlLevelResource) -> bool:
        if not self.access.has_project_access:
            return False
        if level == "manager":
            return self.access.check_can_modify_access_levels_for_object(dashboard)
        return self.access.check_access_level_for_object(dashboard, level) and (
            level != "editor" or self.permissions.dashboard(dashboard).can_edit
        )

    def check(self, dashboard_id: str, level: AccessControlLevelResource) -> bool:
        if dashboard_id not in self.dashboards:
            self.access.preload_access_levels(self.team, "dashboard", resource_id=dashboard_id)
            self.dashboards[dashboard_id] = Dashboard.objects_including_soft_deleted.filter(
                team_id=self.team.id, id=dashboard_id
            ).first()
        dashboard = self.dashboards[dashboard_id]
        return dashboard is not None and self._check(dashboard, level)

    def ids(self, level: AccessControlLevelResource, limit: int) -> frozenset[str] | None:
        dashboards = list(Dashboard.objects.filter(team_id=self.team.id, deleted=False).prefetch_related("privileges"))
        self.access.preload_object_access_controls(dashboards)
        allowed: set[str] = set()
        for dashboard in dashboards:
            if self._check(dashboard, level):
                allowed.add(str(dashboard.id))
                if len(allowed) > limit:
                    return None
        return frozenset(allowed)


def insight_dashboard_ids(team_id: int, insight_ids: Collection[int] | None = None) -> dict[int, tuple[int, ...]]:
    tiles = DashboardTile.objects.filter(team_id=team_id, insight__isnull=False)
    if insight_ids is not None:
        tiles = tiles.filter(insight_id__in=insight_ids)
    result: dict[int, list[int]] = {}
    for insight_id, dashboard_id in tiles.values_list("insight_id", "dashboard_id"):
        if insight_id is not None:
            result.setdefault(insight_id, []).append(dashboard_id)
    return {insight_id: tuple(dashboard_ids) for insight_id, dashboard_ids in result.items()}


def authorization_dashboards(team_id: int) -> tuple[AuthorizationDashboard, ...]:
    dashboards = Dashboard.objects_including_soft_deleted.filter(team_id__exact=team_id)
    return tuple(
        AuthorizationDashboard(
            id=dashboard.id,
            created_by_id=dashboard.created_by_id,
        )
        for dashboard in dashboards
    )
