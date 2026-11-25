from collections.abc import Collection
from datetime import datetime

from django.db.models import Q

from posthog.models.sharing_configuration import SharingConfiguration

from products.dashboards.backend.facade.contracts import InsightPlacement, TilePlacement
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile


def placements_on_dashboards_accessed_since(
    *, placements: Collection[InsightPlacement], since: datetime, shared_only: bool
) -> list[InsightPlacement]:
    if not placements:
        return []
    pairs = Q()
    for placement in placements:
        pairs |= Q(insight_id=placement.insight_id, dashboard_id=placement.dashboard_id)
    # The callers' ids come from cache keys of their own team.
    # nosemgrep: idor-lookup-without-team
    tiles = DashboardTile.objects.filter(dashboard__last_accessed_at__gte=since).filter(pairs)
    if shared_only:
        # A subquery, not the `sharingconfiguration` reverse relation: a relation that crosses a
        # product boundary gets sealed with related_name="+" (products/architecture.md).
        tiles = tiles.filter(
            dashboard_id__in=SharingConfiguration.objects.filter(enabled=True, dashboard_id__isnull=False).values(
                "dashboard_id"
            )
        )
    rows = tiles.distinct().values_list("insight_id", "dashboard_id")
    return [InsightPlacement(insight_id=insight_id, dashboard_id=dashboard_id) for insight_id, dashboard_id in rows]


def live_tile_placements(
    *, dashboard_ids: Collection[int] | None, insight_ids: Collection[int] | None
) -> list[TilePlacement]:
    if dashboard_ids is None and insight_ids is None:
        raise ValueError("Pass dashboard_ids, insight_ids or both, so the read stays bounded.")
    tiles = DashboardTile.objects.all()
    if dashboard_ids is not None:
        tiles = tiles.filter(dashboard_id__in=dashboard_ids)
    if insight_ids is not None:
        tiles = tiles.filter(insight_id__in=insight_ids)
    return [
        TilePlacement(tile_id=tile_id, dashboard_id=dashboard_id, insight_id=insight_id)
        for tile_id, dashboard_id, insight_id in tiles.order_by("id").values_list("id", "dashboard_id", "insight_id")
    ]


def insight_placements(
    *, team_id: int, dashboard_ids: Collection[int], insight_ids: Collection[int] | None, include_deleted: bool
) -> list[InsightPlacement]:
    if not dashboard_ids or (insight_ids is not None and not insight_ids):
        return []
    if include_deleted:
        dashboards = Dashboard.objects_including_soft_deleted.filter(team_id=team_id, id__in=dashboard_ids)
        tiles = DashboardTile.objects_including_soft_deleted.all()
    else:
        dashboards = Dashboard.objects.filter(team_id=team_id, id__in=dashboard_ids)
        tiles = DashboardTile.objects.all()
    tiles = tiles.filter(dashboard__in=dashboards, insight_id__isnull=False)
    if insight_ids is not None:
        tiles = tiles.filter(insight_id__in=insight_ids)
    rows = tiles.order_by("id").values_list("insight_id", "dashboard_id")
    return [InsightPlacement(insight_id=insight_id, dashboard_id=dashboard_id) for insight_id, dashboard_id in rows]


def insight_ids_on_template_dashboards(
    *, insight_ids: Collection[int], name_prefix: str, description_prefix: str
) -> set[int]:
    template_dashboards = Dashboard.objects.filter(
        creation_mode=Dashboard.CreationMode.TEMPLATE,
        name__startswith=name_prefix,
        description__startswith=description_prefix,
    )
    return set(
        DashboardTile.objects.filter(
            insight_id__in=insight_ids, dashboard_id__in=template_dashboards.values("id")
        ).values_list("insight_id", flat=True)
    )


def delete_widget_tiles_for_teams(team_ids: list[int]) -> None:
    # Imported at call time: that module imports many products at load, this one included.
    from posthog.models.team.util import _raw_delete_batch  # noqa: PLC0415

    # The base manager, because the default one hides soft-deleted tiles, and those protect their widget too.
    _raw_delete_batch(DashboardTile._base_manager.filter(team_id__in=team_ids, widget__isnull=False))
