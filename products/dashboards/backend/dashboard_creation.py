"""Create a dashboard and all of its tiles in one transaction, for a product that builds a dashboard for a user.

The product can later move the tiles that it created, for example after it compared the dashboard with its source.
"""

from __future__ import annotations

import hashlib
from base64 import urlsafe_b64encode
from collections.abc import Mapping
from typing import Any

from django.db import transaction

from posthog.models.activity_logging.model_activity import ActingUserContext
from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.facade.contracts import (
    CreatedDashboard,
    DashboardCreationDenied,
    DashboardTileSnapshot,
    NewDashboard,
    NewInsightTile,
    TileLayout,
)
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile, Text
from products.product_analytics.backend.facade.api import get_or_create_saved_insight

MAX_DASHBOARD_NAME_LENGTH = 400


def _insight_short_id(idempotency_key: str, index: int) -> str:
    digest = hashlib.sha256(f"dashboard_creation:{idempotency_key}:{index}".encode()).digest()
    return urlsafe_b64encode(digest[:9]).decode()


def _layouts(layout: TileLayout) -> dict[str, dict[str, int]]:
    # The frontend derives the single-column layout from the order and heights of the desktop one.
    return {"sm": {"x": layout.x, "y": layout.y, "w": layout.w, "h": layout.h}}


def create_dashboard_with_tiles(*, team_id: int, user_id: int, dashboard: NewDashboard) -> CreatedDashboard:
    """Create the dashboard, its insights and its text tiles as the user, or nothing at all.

    Raises `DashboardCreationDenied` when the user cannot edit dashboards, or cannot edit insights
    and the dashboard has insight tiles. Runs in the caller's transaction when there is one.
    """
    team = Team.objects.get(id=team_id)
    user = User.objects.get(id=user_id)
    access = UserAccessControl(user=user, team=team)
    if not access.check_access_level_for_resource("dashboard", "editor"):
        raise DashboardCreationDenied("You need editor access to dashboards to create a dashboard.")
    has_insights = any(isinstance(tile, NewInsightTile) for tile in dashboard.tiles)
    if has_insights and not access.check_access_level_for_resource("insight", "editor"):
        raise DashboardCreationDenied("You need editor access to insights to create the dashboard's insights.")

    insight_count = 0
    text_tile_count = 0
    tile_ids: list[int] = []
    with ActingUserContext(user), transaction.atomic():
        created = Dashboard.objects.create(
            team_id=team_id,
            name=dashboard.name[:MAX_DASHBOARD_NAME_LENGTH],
            description=dashboard.description,
            created_by=user,
            filters={
                **(dashboard.filters or {}),
                **({"date_from": dashboard.date_from} if dashboard.date_from else {}),
            },
            creation_mode=Dashboard.CreationMode.UNLISTED if dashboard.unlisted else Dashboard.CreationMode.DEFAULT,
        )
        for index, tile in enumerate(dashboard.tiles):
            if isinstance(tile, NewInsightTile):
                insight_id, was_created = get_or_create_saved_insight(
                    team_id=team_id,
                    user_id=user_id,
                    short_id=_insight_short_id(dashboard.idempotency_key, index),
                    name=tile.name,
                    description=tile.description,
                    query=tile.query,
                    revive_deleted=False,
                    saved=not dashboard.unlisted,
                )
                if not was_created:
                    raise ValueError("A dashboard was already created with this idempotency key.")
                created_tile = DashboardTile.objects.create(
                    dashboard=created,
                    team_id=team_id,
                    insight_id=insight_id,
                    layouts=_layouts(tile.layout),
                    show_description=tile.show_description,
                )
                insight_count += 1
            else:
                text = Text.objects.create(team_id=team_id, body=tile.body, created_by=user, last_modified_by=user)
                created_tile = DashboardTile.objects.create(
                    dashboard=created, team_id=team_id, text=text, layouts=_layouts(tile.layout)
                )
                text_tile_count += 1
            tile_ids.append(created_tile.id)

    return CreatedDashboard(
        id=created.id, insight_count=insight_count, text_tile_count=text_tile_count, tile_ids=tuple(tile_ids)
    )


def move_dashboard_tiles(*, team_id: int, user_id: int, dashboard_id: int, layouts: Mapping[int, TileLayout]) -> int:
    """Set the desktop box of tiles on a dashboard, as the user. Returns how many tiles moved.

    Raises `DashboardCreationDenied` when the user cannot edit the dashboard. Ignores a tile id that
    is not on the dashboard, or that is deleted.
    """
    team = Team.objects.get(id=team_id)
    user = User.objects.get(id=user_id)
    dashboard = Dashboard.objects.filter(team_id=team_id, id=dashboard_id, deleted=False).first()
    if dashboard is None:
        return 0
    if not UserAccessControl(user=user, team=team).check_access_level_for_object(dashboard, "editor"):
        raise DashboardCreationDenied("You need editor access to this dashboard to move its tiles.")
    moved = 0
    with ActingUserContext(user), transaction.atomic():
        tiles = DashboardTile.objects.filter(
            team_id=team_id, dashboard_id=dashboard_id, id__in=list(layouts)
        ).select_for_update()
        for tile in tiles:
            tile.layouts = _layouts(layouts[tile.id])
            tile.save(update_fields=["layouts"])
            moved += 1
    return moved


def _snapshot_layout(layouts: object) -> TileLayout | None:
    box = layouts.get("sm") if isinstance(layouts, dict) else None
    if not isinstance(box, dict):
        return None
    try:
        return TileLayout(x=int(box["x"]), y=int(box["y"]), w=int(box["w"]), h=int(box["h"]))
    except (KeyError, TypeError, ValueError):
        return None


def read_dashboard_tiles(*, team_id: int, dashboard_id: int) -> tuple[DashboardTileSnapshot, ...]:
    """The live insight and text tiles of a dashboard, top to bottom. Other tile kinds are left out."""
    tiles = (
        DashboardTile.objects.filter(team_id=team_id, dashboard_id=dashboard_id)
        .select_related("insight", "text")
        .order_by("id")
    )
    snapshots: list[DashboardTileSnapshot] = []
    for tile in tiles:
        layout = _snapshot_layout(tile.layouts)
        if tile.insight is not None and not tile.insight.deleted:
            snapshots.append(
                DashboardTileSnapshot(
                    tile_id=tile.id,
                    layout=layout,
                    name=tile.insight.name or tile.insight.derived_name or "",
                    description=tile.insight.description or "",
                    query=tile.insight.query,
                )
            )
        elif tile.text is not None:
            snapshots.append(DashboardTileSnapshot(tile_id=tile.id, layout=layout, body=tile.text.body or ""))
    return tuple(
        sorted(snapshots, key=lambda snapshot: (snapshot.layout.y, snapshot.layout.x) if snapshot.layout else (0, 0))
    )


def read_dashboard_metric_variables(*, team_id: int, dashboard_id: int) -> list[dict[str, Any]]:
    """The metrics dashboard variables of a dashboard, as MetricsDashboardVariable JSON."""
    filters = (
        Dashboard.objects.filter(team_id=team_id, id=dashboard_id, deleted=False)
        .values_list("filters", flat=True)
        .first()
    )
    variables = filters.get("metricVariables") if isinstance(filters, dict) else None
    return [variable for variable in variables if isinstance(variable, dict)] if isinstance(variables, list) else []


def delete_unlisted_dashboard(*, team_id: int, dashboard_id: int) -> bool:
    """Soft-delete an unlisted dashboard that a product created. Returns False when there is no such dashboard."""
    deleted = Dashboard.objects.filter(
        team_id=team_id, id=dashboard_id, creation_mode=Dashboard.CreationMode.UNLISTED, deleted=False
    ).update(deleted=True)
    return deleted > 0
