"""Test-support facade for dashboards.

Suites outside this product plant dashboard and tile rows through here instead of importing the
models. Each `create_*` helper returns the new row's id. Read rows back through `facade.api` where
it has a read, and through the readers here for the columns only tests look at.

An async test wraps a helper in `sync_to_async`.
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from unittest.mock import patch

from prometheus_client import REGISTRY

from posthog.models.tag import Tag

from products.dashboards.backend.facade.contracts import (
    DashboardExtras,
    DashboardWidgetTile,
    InsightTileState,
    PlantedWidgetTile,
)
from products.dashboards.backend.facade.enums import (
    DashboardAccessMethod,
    DashboardCreationMode,
    DashboardTemplateScope,
)
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_templates import DashboardTemplate
from products.dashboards.backend.models.dashboard_tile import ButtonTile, DashboardTile, Text
from products.dashboards.backend.models.dashboard_widget import DashboardWidget
from products.dashboards.backend.models.team_home_tab_dashboard_config import TeamHomeTabDashboardConfig

__all__ = [
    "UNSET",
    "create_button_tile",
    "create_dashboard",
    "create_dashboard_template",
    "create_insight_tile",
    "create_text_tile",
    "create_widget_tile",
    "dashboard_access_count",
    "dashboard_extras",
    "dashboard_ids",
    "dashboard_template_name",
    "delete_dashboard",
    "delete_global_dashboard_templates",
    "delete_tile",
    "global_dashboard_template_exists",
    "home_tab_config_exists",
    "insight_tile_is_deleted",
    "insight_tile_states",
    "set_tile_deleted",
    "tile_ids",
    "update_dashboard",
    "widget_creation_flags_enabled",
    "widget_tile_creation_fails",
    "widget_tiles",
]


class _Unset(Enum):
    UNSET = "unset"


# Marks a keyword the caller left out, where None is a value the caller can write.
UNSET = _Unset.UNSET


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
    share_token: str | None = None,
    is_shared: bool = False,
    quick_filter_ids: list[str] | None | _Unset = UNSET,
    created_at: datetime | None = None,
    tags: Sequence[str] = (),
) -> int:
    """Create a dashboard with no tiles, and return its id. `tags` names tags to create or reuse."""
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
        share_token=share_token,
        is_shared=is_shared,
        **({} if quick_filter_ids is UNSET else {"quick_filter_ids": quick_filter_ids}),
    )
    if created_at is not None:
        # `created_at` is auto_now_add, so the insert ignores a value passed to it.
        Dashboard.objects_including_soft_deleted.filter(id=dashboard.id).update(created_at=created_at)
    for tag_name in tags:
        tag, _ = Tag.objects.get_or_create(name=tag_name, team_id=dashboard.team_id)
        dashboard.tagged_items.create(tag_id=tag.id)
    return dashboard.id


def update_dashboard(
    *,
    dashboard_id: int,
    name: str | None | _Unset = UNSET,
    description: str | _Unset = UNSET,
    filters: dict[str, Any] | _Unset = UNSET,
    variables: dict[str, Any] | None | _Unset = UNSET,
    deleted: bool | _Unset = UNSET,
    created_by_id: int | None | _Unset = UNSET,
    last_accessed_at: datetime | None | _Unset = UNSET,
    share_token: str | None | _Unset = UNSET,
    is_shared: bool | _Unset = UNSET,
    quick_filter_ids: list[str] | None | _Unset = UNSET,
) -> None:
    """Change the passed columns of a dashboard, soft-deleted or not.

    Saves the row, so the file-system sync and the activity log see the change.
    """
    dashboard = Dashboard.objects_including_soft_deleted.get(id=dashboard_id)
    changes: dict[str, Any] = {
        "name": name,
        "description": description,
        "filters": filters,
        "variables": variables,
        "deleted": deleted,
        "created_by_id": created_by_id,
        "last_accessed_at": last_accessed_at,
        "share_token": share_token,
        "is_shared": is_shared,
        "quick_filter_ids": quick_filter_ids,
    }
    changed = {field: value for field, value in changes.items() if value is not UNSET}
    for field, value in changed.items():
        setattr(dashboard, field, value)
    dashboard.save(update_fields=list(changed))


def delete_dashboard(*, dashboard_id: int) -> None:
    """Hard-delete a dashboard, so its tiles and the rows that point at it go with it."""
    Dashboard.objects_including_soft_deleted.get(id=dashboard_id).delete()


def dashboard_ids(*, team_id: int, name: str | None = None, include_deleted: bool = False) -> list[int]:
    """Ids of the team's dashboards, oldest first. An environment reads its project's dashboards."""
    manager = Dashboard.objects_including_soft_deleted if include_deleted else Dashboard.objects
    dashboards = manager.filter(team_id=team_id)
    if name is not None:
        dashboards = dashboards.filter(name=name)
    return list(dashboards.order_by("id").values_list("id", flat=True))


def dashboard_extras(*, dashboard_id: int) -> DashboardExtras:
    dashboard = Dashboard.objects_including_soft_deleted.get(id=dashboard_id)
    return DashboardExtras(
        share_token=dashboard.share_token,
        is_shared=dashboard.is_shared,
        quick_filter_ids=dashboard.quick_filter_ids,
    )


def home_tab_config_exists(*, team_id: int) -> bool:
    """Whether the team has a Home tab config row, whatever dashboard it points at."""
    return TeamHomeTabDashboardConfig.objects.for_team(team_id).exists()


def create_insight_tile(
    *,
    dashboard_id: int,
    insight_id: int,
    layouts: dict[str, Any] | None = None,
    color: str | None = None,
    filters_overrides: dict[str, Any] | None = None,
    deleted: bool = False,
    refresh_attempt: int | None = None,
) -> int:
    """Place an insight on a dashboard, and return the tile's id. `deleted` plants a removed tile."""
    tile = DashboardTile.objects.create(
        dashboard_id=dashboard_id,
        insight_id=insight_id,
        layouts=layouts or {},
        color=color,
        filters_overrides=filters_overrides if filters_overrides is not None else {},
        deleted=deleted,
        refresh_attempt=refresh_attempt,
    )
    return tile.id


def create_text_tile(
    *,
    dashboard_id: int,
    body: str,
    layouts: dict[str, Any] | None = None,
    created_by_id: int | None = None,
    agent_context: str | None = None,
) -> int:
    """Add a text card to a dashboard, and return the tile's id."""
    dashboard = Dashboard.objects_including_soft_deleted.get(id=dashboard_id)
    text = Text.objects.create(
        team_id=dashboard.team_id, body=body, created_by_id=created_by_id, agent_context=agent_context
    )
    tile = DashboardTile.objects.create(dashboard=dashboard, text=text, layouts=layouts or {})
    return tile.id


def create_button_tile(
    *,
    dashboard_id: int,
    url: str,
    text: str,
    created_by_id: int | None = None,
    layouts: dict[str, Any] | None = None,
) -> int:
    """Add a button tile to a dashboard, and return the tile's id."""
    dashboard = Dashboard.objects_including_soft_deleted.get(id=dashboard_id)
    button = ButtonTile.objects.create(team_id=dashboard.team_id, url=url, text=text, created_by_id=created_by_id)
    tile = DashboardTile.objects.create(dashboard=dashboard, button_tile=button, layouts=layouts or {})
    return tile.id


def create_widget_tile(
    *,
    dashboard_id: int,
    widget_type: str,
    config: dict[str, Any] | None = None,
    name: str | None = None,
    created_by_id: int | None = None,
    layouts: dict[str, Any] | None = None,
    deleted: bool = False,
) -> PlantedWidgetTile:
    """Add a widget and the tile that shows it, without the checks the widget API runs on the type and config."""
    dashboard = Dashboard.objects_including_soft_deleted.get(id=dashboard_id)
    widget = DashboardWidget.objects.for_team(dashboard.team_id).create(
        team_id=dashboard.team_id,
        widget_type=widget_type,
        name=name,
        config=config or {},
        created_by_id=created_by_id,
    )
    tile = DashboardTile.objects.create(dashboard=dashboard, widget=widget, layouts=layouts or {}, deleted=deleted)
    return PlantedWidgetTile(tile_id=tile.id, widget_id=widget.id)


def set_tile_deleted(*, tile_id: int, deleted: bool = True) -> None:
    """Remove a tile of any kind from its dashboard, or restore it, the way the app does."""
    tile = DashboardTile.objects_including_soft_deleted.get(id=tile_id)
    tile.deleted = deleted
    tile.save(update_fields=["deleted"])


def delete_tile(*, tile_id: int) -> None:
    """Hard-delete a tile row."""
    DashboardTile.objects_including_soft_deleted.get(id=tile_id).delete()


def tile_ids(
    *, dashboard_id: int | None = None, insight_id: int | None = None, include_removed: bool = False
) -> list[int]:
    """Ids of the tiles of any kind that match, oldest first.

    Without `include_removed`, a tile counts only while it and its dashboard are live.
    """
    tiles = DashboardTile.objects_including_soft_deleted if include_removed else DashboardTile.objects
    matching = tiles.all()
    if dashboard_id is not None:
        matching = matching.filter(dashboard_id=dashboard_id)
    if insight_id is not None:
        matching = matching.filter(insight_id=insight_id)
    return list(matching.order_by("id").values_list("id", flat=True))


def insight_tile_states(
    *, dashboard_id: int | None = None, insight_id: int | None = None, include_removed: bool = False
) -> list[InsightTileState]:
    """The insight tiles that match, oldest first, with the columns tests assert on."""
    tiles = DashboardTile.objects_including_soft_deleted if include_removed else DashboardTile.objects
    matching = tiles.filter(insight_id__isnull=False)
    if dashboard_id is not None:
        matching = matching.filter(dashboard_id=dashboard_id)
    if insight_id is not None:
        matching = matching.filter(insight_id=insight_id)
    return [
        InsightTileState(
            tile_id=tile.id,
            dashboard_id=tile.dashboard_id,
            insight_id=tile.insight_id,
            layouts=tile.layouts or {},
            color=tile.color,
            filters_overrides=tile.filters_overrides,
            # The column is nullable, and a tile that was never removed holds null.
            deleted=bool(tile.deleted),
        )
        for tile in matching.order_by("id")
        if tile.insight_id is not None
    ]


def insight_tile_is_deleted(*, dashboard_id: int, insight_id: int) -> bool | None:
    """Whether the tile that places this insight on this dashboard is removed, or None when there is no tile."""
    flags = list(
        DashboardTile.objects_including_soft_deleted.filter(dashboard_id=dashboard_id, insight_id=insight_id)
        .values_list("deleted", flat=True)
        .order_by("id")[:1]
    )
    # The column is nullable, and a tile that was never removed holds null.
    return bool(flags[0]) if flags else None


def widget_tiles(*, dashboard_id: int) -> list[DashboardWidgetTile]:
    """The live widget tiles of a dashboard, oldest first."""
    tiles = DashboardTile.objects.filter(dashboard_id=dashboard_id, widget__isnull=False).select_related("widget")
    return [
        DashboardWidgetTile(
            tile_id=tile.id,
            widget_type=tile.widget.widget_type,
            name=tile.widget.name,
            config=tile.widget.config,
        )
        for tile in tiles.order_by("id")
        if tile.widget is not None
    ]


@contextmanager
def widget_creation_flags_enabled() -> Iterator[None]:
    """Treat every widget feature flag as on while creating widget tiles inside the block."""
    with patch("products.dashboards.backend.widget_create.widget_flag_enabled", return_value=True):
        yield


@contextmanager
def widget_tile_creation_fails(error: Exception) -> Iterator[None]:
    """Make publishing a widget to a dashboard raise `error` where it creates the tile."""
    with patch("products.dashboards.backend.widget_publication.create_widget_tile", side_effect=error):
        yield


def create_dashboard_template(
    *,
    template_name: str,
    scope: DashboardTemplateScope | None = None,
    team_id: int | None = None,
    dashboard_description: str = "",
    tiles: list[dict[str, Any]] | None = None,
    tags: list[str] | None = None,
) -> UUID:
    """Store a dashboard template, and return its id. Without `team_id` every project can use it."""
    template = DashboardTemplate.objects.create(
        template_name=template_name,
        scope=scope.value if scope is not None else None,
        team_id=team_id,
        dashboard_description=dashboard_description,
        tiles=tiles or [],
        tags=tags or [],
    )
    return template.id


def dashboard_template_name(*, template_id: UUID) -> str | None:
    """The name of a live template, or None when no live template has this id."""
    # nosemgrep: idor-lookup-without-team (test support: a global template has no team to filter on)
    return DashboardTemplate.objects.filter(id=template_id).values_list("template_name", flat=True).first()


def global_dashboard_template_exists(*, template_name: str) -> bool:
    return DashboardTemplate.objects.filter(template_name=template_name, team__isnull=True).exists()


def delete_global_dashboard_templates(*, template_name: str) -> None:
    DashboardTemplate.objects_including_soft_deleted.filter(template_name=template_name, team__isnull=True).delete()


def dashboard_access_count(access_method: DashboardAccessMethod) -> float:
    """How many dashboard accesses this process has counted under `access_method`. Read it before and after."""
    return REGISTRY.get_sample_value("posthog_dashboard_access_total", {"access_method": access_method.value}) or 0.0
