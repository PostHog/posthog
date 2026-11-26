from collections.abc import Collection, Sequence
from typing import Any

from django.db import router
from django.utils.timezone import now

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.facade.models import Insight


def create_insight_tile(
    *, dashboard_id: int, insight_id: int, layouts: dict[str, Any] | None, color: str | None
) -> int:
    tile = DashboardTile.objects.create(
        dashboard_id=dashboard_id, insight_id=insight_id, layouts=layouts or {}, color=color
    )
    return tile.id


def create_insight_tiles(*, insight_id: int, team_id: int, dashboard_ids: Sequence[int]) -> None:
    if not dashboard_ids:
        return
    # DashboardTile.save reads the tile's insight, and its dashboard when the insight has legacy filters.
    # Load both once here, so that placing an insight on N dashboards does not read them N times. The
    # caller may have just created the insight, so read from the writer: a lagging replica would miss it.
    writer = router.db_for_write(Insight)
    insight = Insight.objects_including_soft_deleted.using(writer).get(pk=insight_id, team_id=team_id)
    dashboards = (
        Dashboard.objects_including_soft_deleted.using(writer).in_bulk(dashboard_ids) if insight.filters else {}
    )
    for dashboard_id in dashboard_ids:
        tile = DashboardTile(insight=insight, dashboard_id=dashboard_id, team_id=team_id, last_refresh=now())
        if dashboard_id in dashboards:
            tile.dashboard = dashboards[dashboard_id]
        tile.save()


def restore_or_create_insight_tile(*, dashboard: Dashboard, insight_id: int) -> tuple[DashboardTile, bool]:
    """The insight's tile on this dashboard, and whether this call put it there.

    A removed tile is restored rather than duplicated, so it keeps its layout.
    """
    tile, created = DashboardTile.objects_including_soft_deleted.get_or_create(
        dashboard=dashboard, insight_id=insight_id
    )
    if tile.deleted:
        tile.deleted = False
        tile.save()
        return tile, True
    return tile, created


def remove_insight_tiles(*, insight_id: int, dashboard_ids: Collection[int]) -> tuple[int, ...]:
    """Soft-delete the insight's live tiles on these dashboards, and return the dashboards whose tile was live."""
    # Capture the still-active tiles before soft-deleting so the caller can report one
    # removal per tile that is actually removed.
    tiles_to_remove = list(DashboardTile.objects.filter(dashboard_id__in=dashboard_ids, insight_id=insight_id))
    DashboardTile.objects.filter(dashboard_id__in=dashboard_ids, insight_id=insight_id).update(deleted=True)
    return tuple(tile.dashboard_id for tile in tiles_to_remove)


def hide_tiles_for_insights(insight_ids: Collection[int]) -> None:
    DashboardTile.objects_including_soft_deleted.filter(insight_id__in=insight_ids).update(deleted=True)


def restore_tiles(tile_ids: Collection[int]) -> None:
    DashboardTile.objects_including_soft_deleted.filter(id__in=tile_ids).update(deleted=False)


def restore_tiles_on_live_dashboards(insight_ids: Collection[int]) -> None:
    DashboardTile.objects_including_soft_deleted.filter(
        insight_id__in=insight_ids, deleted=True, dashboard__deleted=False
    ).update(deleted=False)
