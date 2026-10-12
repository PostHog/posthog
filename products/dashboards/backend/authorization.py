from posthog.settings import EE_AVAILABLE
from posthog.user_permissions import UserPermissions

from products.access_control.backend.facade.user_access_control import AccessControlLevelResource, UserAccessControl
from products.dashboards.backend.facade.authorization_contracts import AuthorizationDashboard
from products.dashboards.backend.facade.enums import PrivilegeLevel, RestrictionLevel
from products.dashboards.backend.models.dashboard import Dashboard


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
            self.dashboards[dashboard_id] = Dashboard.objects.filter(team_id=self.team.id, id=dashboard_id).first()
        dashboard = self.dashboards[dashboard_id]
        return dashboard is not None and self._check(dashboard, level)

    def ids(self, level: AccessControlLevelResource, limit: int | None) -> frozenset[str] | None:
        ids: set[str] = set()
        # ponytail: full dashboard scan; use queryset filtering before a production rollout.
        for dashboard in Dashboard.objects.filter(team_id=self.team.id):
            if self._check(dashboard, level):
                ids.add(str(dashboard.id))
                if limit is not None and len(ids) > limit:
                    return None
        return frozenset(ids)


def authorization_dashboards(team_id: int) -> tuple[AuthorizationDashboard, ...]:
    dashboards = Dashboard.objects.filter(team_id__exact=team_id)
    if EE_AVAILABLE:
        dashboards = dashboards.prefetch_related("privileges")
    return tuple(
        AuthorizationDashboard(
            id=dashboard.id,
            created_by_id=dashboard.created_by_id,
            restricted=dashboard.restriction_level == RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
            collaborator_user_ids=tuple(
                privilege.user_id
                for privilege in dashboard.privileges.all()
                if privilege.level >= PrivilegeLevel.CAN_EDIT
            )
            if EE_AVAILABLE
            else (),
        )
        for dashboard in dashboards
    )
