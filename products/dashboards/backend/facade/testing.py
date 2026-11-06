"""Test-support facade for dashboards.

Suites outside this product plant dashboard and tile rows through here instead of importing the
models. Each helper returns the new row's id; read rows back through `facade.api`.
"""

from datetime import datetime
from typing import Any

from products.dashboards.backend.facade.enums import DashboardCreationMode
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile, Text

__all__ = [
    "create_dashboard",
    "create_insight_tile",
    "create_text_tile",
    "insight_tile_is_deleted",
]


def create_dashboard(
    *,
    team_id: int,
    name: str | None = None,
    description: str = "",
    created_by_id: int | None = None,
    deleted: bool = False,
    pinned: bool = False,
    creation_mode: DashboardCreationMode = DashboardCreationMode.DEFAULT,
    last_accessed_at: datetime | None = None,
    filters: dict[str, Any] | None = None,
    variables: dict[str, Any] | None = None,
) -> int:
    """Create a dashboard with no tiles, and return its id."""
    dashboard = Dashboard.objects.create(
        team_id=team_id,
        name=name,
        description=description,
        created_by_id=created_by_id,
        deleted=deleted,
        pinned=pinned,
        creation_mode=creation_mode.value,
        last_accessed_at=last_accessed_at,
        filters=filters or {},
        variables=variables if variables is not None else {},
    )
    return dashboard.id


def create_insight_tile(
    *,
    dashboard_id: int,
    insight_id: int,
    layouts: dict[str, Any] | None = None,
    color: str | None = None,
    filters_overrides: dict[str, Any] | None = None,
    deleted: bool = False,
) -> int:
    """Place an insight on a dashboard, and return the tile's id. `deleted` plants a removed tile."""
    tile = DashboardTile.objects.create(
        dashboard_id=dashboard_id,
        insight_id=insight_id,
        layouts=layouts or {},
        color=color,
        filters_overrides=filters_overrides if filters_overrides is not None else {},
        deleted=deleted,
    )
    return tile.id


def create_text_tile(*, dashboard_id: int, body: str, layouts: dict[str, Any] | None = None) -> int:
    """Add a text card to a dashboard, and return the tile's id."""
    dashboard = Dashboard.objects_including_soft_deleted.get(id=dashboard_id)
    text = Text.objects.create(team_id=dashboard.team_id, body=body)
    tile = DashboardTile.objects.create(dashboard=dashboard, text=text, layouts=layouts or {})
    return tile.id


def insight_tile_is_deleted(*, dashboard_id: int, insight_id: int) -> bool | None:
    """Whether the tile that places this insight on this dashboard is removed, or None when there is no tile."""
    flags = list(
        DashboardTile.objects_including_soft_deleted.filter(dashboard_id=dashboard_id, insight_id=insight_id)
        .values_list("deleted", flat=True)
        .order_by("id")[:1]
    )
    # The column is nullable, and a tile that was never removed holds null.
    return bool(flags[0]) if flags else None
