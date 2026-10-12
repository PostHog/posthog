from products.dashboards.backend.models.dashboard import Dashboard


def create_dashboard(*, team_id: int, created_by_id: int | None = None) -> int:
    return Dashboard.objects.create(team_id=team_id, created_by_id=created_by_id).id


def set_dashboard_deleted(*, team_id: int, dashboard_id: int, deleted: bool) -> None:
    dashboard = Dashboard.objects_including_soft_deleted.get(team_id__exact=team_id, id=dashboard_id)
    dashboard.deleted = deleted
    dashboard.save(update_fields=["deleted"])


def delete_dashboard(*, team_id: int, dashboard_id: int) -> None:
    Dashboard.objects_including_soft_deleted.get(team_id__exact=team_id, id=dashboard_id).delete()
