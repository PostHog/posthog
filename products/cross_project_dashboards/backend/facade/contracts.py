"""Contract types for cross_project_dashboards: what the facade returns to the API and MCP tools.

No Django imports.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic.dataclasses import dataclass


class DashboardNotFoundError(Exception):
    """The dashboard does not exist, is deleted, or belongs to another organization."""


class DashboardChangeDeniedError(Exception):
    """The dashboard holds tiles from a project the user cannot open, so the user cannot change or delete it."""


class TileNotFoundError(Exception):
    """The tile does not exist, is deleted, or is in a project the reader cannot open."""


@dataclass(frozen=True)
class DashboardCreator:
    id: int
    first_name: str
    email: str


@dataclass(frozen=True)
class CrossProjectTile:
    id: UUID
    project_id: int
    insight_id: int
    layouts: dict[str, Any]
    color: str | None
    filters_overrides: dict[str, Any]


@dataclass(frozen=True)
class CrossProjectDashboard:
    id: UUID
    name: str
    description: str
    filters: dict[str, Any]
    tiles: list[CrossProjectTile]
    created_by: DashboardCreator | None
    created_at: datetime
    updated_at: datetime | None


@dataclass(frozen=True)
class CrossProjectDashboardSummary:
    """A list row. It counts the tiles instead of carrying them, so a page stays small."""

    id: UUID
    name: str
    description: str
    filters: dict[str, Any]
    tile_count: int
    project_count: int
    created_by: DashboardCreator | None
    created_at: datetime
    updated_at: datetime | None


@dataclass(frozen=True)
class DashboardPage:
    results: list[CrossProjectDashboardSummary]
    count: int


@dataclass(frozen=True)
class TilePage:
    results: list[CrossProjectTile]
    count: int


@dataclass(frozen=True)
class NewDashboard:
    name: str
    description: str
    filters: dict[str, Any]


@dataclass(frozen=True)
class DashboardChanges:
    """A partial update. Only the fields named in `fields` change."""

    fields: frozenset[str]
    name: str = ""
    description: str = ""
    filters: dict[str, Any] | None = None


@dataclass(frozen=True)
class NewTile:
    project_id: int
    insight_id: int
    layouts: dict[str, Any]
    color: str | None
    filters_overrides: dict[str, Any]


@dataclass(frozen=True)
class TileChanges:
    """A partial update. Only the fields named in `fields` change, so a tile's color can be set to null."""

    fields: frozenset[str]
    layouts: dict[str, Any] | None = None
    color: str | None = None
    filters_overrides: dict[str, Any] | None = None
