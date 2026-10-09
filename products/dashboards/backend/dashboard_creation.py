"""Create a dashboard and all of its tiles in one transaction, for a product that builds a dashboard for a user."""

from __future__ import annotations

import hashlib
from base64 import urlsafe_b64encode
from typing import Any

from django.db import transaction

from posthog.dataclasses import frozen
from posthog.models.activity_logging.model_activity import ActingUserContext
from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile, Text
from products.product_analytics.backend.facade.api import get_or_create_saved_insight

GRID_COLUMNS = 12
MAX_DASHBOARD_NAME_LENGTH = 400
MAX_TEXT_TILE_LENGTH = 4000


class DashboardCreationDenied(Exception):
    """The user cannot create a dashboard or its insights in this project. The message is safe to show."""


@frozen
class TileLayout:
    """A tile box on the 12-column desktop grid."""

    x: int
    y: int
    w: int
    h: int

    def __post_init__(self) -> None:
        if self.x < 0 or self.y < 0 or self.w < 1 or self.h < 1 or self.x + self.w > GRID_COLUMNS:
            raise ValueError(f"The tile box {self} does not fit the {GRID_COLUMNS}-column grid.")


@frozen
class NewInsightTile:
    name: str
    description: str
    query: dict[str, Any]
    layout: TileLayout


@frozen
class NewTextTile:
    body: str
    layout: TileLayout

    def __post_init__(self) -> None:
        if len(self.body) > MAX_TEXT_TILE_LENGTH:
            raise ValueError(f"A text tile can hold at most {MAX_TEXT_TILE_LENGTH} characters.")


@frozen
class NewDashboard:
    name: str
    description: str
    tiles: tuple[NewInsightTile | NewTextTile, ...]
    # Seeds the insight short ids. A second creation with the same key collides on them and rolls back,
    # so a retried job cannot leave two copies of the same dashboard.
    idempotency_key: str
    date_from: str | None = None


@frozen
class CreatedDashboard:
    id: int
    insight_count: int
    text_tile_count: int


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
    with ActingUserContext(user), transaction.atomic():
        created = Dashboard.objects.create(
            team_id=team_id,
            name=dashboard.name[:MAX_DASHBOARD_NAME_LENGTH],
            description=dashboard.description,
            created_by=user,
            filters={"date_from": dashboard.date_from} if dashboard.date_from else {},
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
                )
                if not was_created:
                    raise ValueError("A dashboard was already created with this idempotency key.")
                DashboardTile.objects.create(
                    dashboard=created, team_id=team_id, insight_id=insight_id, layouts=_layouts(tile.layout)
                )
                insight_count += 1
            else:
                text = Text.objects.create(team_id=team_id, body=tile.body, created_by=user, last_modified_by=user)
                DashboardTile.objects.create(
                    dashboard=created, team_id=team_id, text=text, layouts=_layouts(tile.layout)
                )
                text_tile_count += 1

    return CreatedDashboard(id=created.id, insight_count=insight_count, text_tile_count=text_tile_count)
