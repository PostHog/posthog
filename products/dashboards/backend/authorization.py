from posthog.settings import EE_AVAILABLE

from products.dashboards.backend.facade.authorization_contracts import AuthorizationDashboard
from products.dashboards.backend.facade.enums import PrivilegeLevel, RestrictionLevel
from products.dashboards.backend.models.dashboard import Dashboard


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
