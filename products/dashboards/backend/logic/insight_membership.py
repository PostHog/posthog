from collections.abc import Collection, Sequence
from typing import Any

from django.utils.timezone import now

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile


def create_insight_tile(
    *, dashboard_id: int, insight_id: int, layouts: dict[str, Any] | None, color: str | None
) -> int:
    tile = DashboardTile.objects.create(
        dashboard_id=dashboard_id, insight_id=insight_id, layouts=layouts or {}, color=color
    )
    return tile.id


def create_insight_tiles(*, insight_id: int, team_id: int, dashboard_ids: Sequence[int]) -> None:
    for dashboard_id in dashboard_ids:
        DashboardTile.objects.create(
            insight_id=insight_id, dashboard_id=dashboard_id, team_id=team_id, last_refresh=now()
        )


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
