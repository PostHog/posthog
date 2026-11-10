from datetime import datetime

from django.db.models import Count, F, QuerySet

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.facade.contracts import TeamDashboardRef
from products.dashboards.backend.facade.enums import DashboardUsageCount
from products.dashboards.backend.models.dashboard import Dashboard

# Generated dashboards carry this in their name. The weekly digest lists only dashboards people made.
GENERATED_DASHBOARD_NAME_MARKER = "Generated Dashboard"


def counts_by_team(count: DashboardUsageCount) -> dict[int, int]:
    """Live dashboards per team id, in team id order.

    A shared dashboard counts once per enabled sharing configuration, and a tagged dashboard once
    per tag, because the counts join through those rows.
    """
    dashboards: QuerySet[Dashboard] = Dashboard.objects.all()
    match count:
        case DashboardUsageCount.ALL:
            pass
        case DashboardUsageCount.FROM_TEMPLATE:
            dashboards = dashboards.filter(creation_mode=Dashboard.CreationMode.TEMPLATE)
        case DashboardUsageCount.SHARED:
            dashboards = dashboards.filter(sharingconfiguration__enabled=True)
        case DashboardUsageCount.TAGGED:
            dashboards = dashboards.filter(tagged_items__isnull=False)
    rows = dashboards.values("team_id").annotate(total=Count("id")).order_by("team_id").values_list("team_id", "total")
    return dict(rows)


def created_between(*, period_start: datetime, period_end: datetime, team_ids: range) -> list[TeamDashboardRef]:
    rows = (
        Dashboard.objects.filter(
            created_at__gt=period_start,
            created_at__lte=period_end,
            # `team_id__gte` is not the root-team filter, so this reads the rows stored on these team ids.
            team_id__gte=team_ids.start,
            team_id__lt=team_ids.stop,
        )
        .exclude(name__contains=GENERATED_DASHBOARD_NAME_MARKER)
        .values_list("team_id", "id", "name")
    )
    return [TeamDashboardRef(team_id=team_id, id=dashboard_id, name=name) for team_id, dashboard_id, name in rows]


def has_user_created_dashboard(*, team_id: int) -> bool:
    # `team__id`, not `team_id`, so the root-team filter does not widen the match to the project.
    return Dashboard.objects.filter(team__id=team_id, created_by__isnull=False).exists()


def by_last_access(*, team_ids: list[int], user_access_control: UserAccessControl, limit: int) -> list[Dashboard]:
    dashboards = user_access_control.filter_queryset_by_access_level(
        Dashboard.objects.filter(team_id__in=team_ids), include_all_if_admin=True
    )
    return list(dashboards.order_by(F("last_accessed_at").desc(nulls_last=True), "-created_at")[:limit])
