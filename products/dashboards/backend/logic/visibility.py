from collections.abc import Collection

from django.db.models import Q

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.models.dashboard import Dashboard


def hidden_dashboard_ids(
    *, team_id: int, dashboard_ids: Collection[int], user_access_control: UserAccessControl, include_deleted: bool
) -> set[int]:
    if not dashboard_ids:
        return set()
    manager = Dashboard.objects_including_soft_deleted if include_deleted else Dashboard.objects
    dashboards = manager.filter(team_id=team_id, id__in=dashboard_ids)
    has_resource_access = user_access_control.has_resource_access("dashboard")
    if has_resource_access:
        dashboards = dashboards.filter(
            id__in=user_access_control.blocked_resource_ids_by_scope.get("dashboard", frozenset())
        )
    viewable = user_access_control.filter_queryset_by_access_level(
        dashboards, include_all_if_admin=True, resource="dashboard"
    )
    if not (user_access_control.is_organization_admin or has_resource_access):
        allowed_ids = user_access_control.allowlisted_resource_ids_by_scope.get("dashboard", frozenset())
        viewable = viewable.filter(Q(id__in=allowed_ids) | Q(created_by=user_access_control.user))
    return set(dashboards.exclude(id__in=viewable.values("id")).values_list("id", flat=True))
