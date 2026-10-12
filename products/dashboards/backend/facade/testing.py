from products.dashboards.backend.facade.enums import PrivilegeLevel, RestrictionLevel
from products.dashboards.backend.models.dashboard import Dashboard

from ee.models.dashboard_privilege import DashboardPrivilege


def create_dashboard(*, team_id: int, created_by_id: int | None = None) -> int:
    return Dashboard.objects.create(team_id=team_id, created_by_id=created_by_id).id


def set_dashboard_creator(*, team_id: int, dashboard_id: int, user_id: int | None) -> None:
    dashboard = Dashboard.objects.get(team_id=team_id, id=dashboard_id)
    dashboard.created_by_id = user_id
    dashboard.save(update_fields=["created_by"])


def set_dashboard_restriction(*, team_id: int, dashboard_id: int, level: RestrictionLevel) -> None:
    dashboard = Dashboard.objects.get(team_id=team_id, id=dashboard_id)
    dashboard.restriction_level = level
    dashboard.save(update_fields=["restriction_level"])


def set_dashboard_collaborator(*, team_id: int, dashboard_id: int, user_id: int, level: PrivilegeLevel | None) -> None:
    dashboard = Dashboard.objects.get(team_id=team_id, id=dashboard_id)
    if level is None:
        DashboardPrivilege.objects.filter(dashboard=dashboard, user_id=user_id).delete()
    else:
        DashboardPrivilege.objects.update_or_create(dashboard=dashboard, user_id=user_id, defaults={"level": level})


def set_dashboard_deleted(*, team_id: int, dashboard_id: int, deleted: bool) -> None:
    dashboard = Dashboard.objects_including_soft_deleted.get(team_id__exact=team_id, id=dashboard_id)
    dashboard.deleted = deleted
    dashboard.save(update_fields=["deleted"])


def delete_dashboard(*, team_id: int, dashboard_id: int) -> None:
    Dashboard.objects_including_soft_deleted.get(team_id__exact=team_id, id=dashboard_id).delete()
