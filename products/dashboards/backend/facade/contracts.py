"""
Contract types for dashboards.

Frozen dataclasses, errors and the `AppliedDashboard` protocol that cross the dashboards boundary.
No Django imports: the facade maps dashboard and tile rows to these, and callers outside the
product hold only these.
"""

from dataclasses import field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from pydantic.dataclasses import dataclass

from posthog.dataclasses import frozen

from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.dashboards.backend.facade.enums import DashboardCreationMode, DashboardTemplateScope

GRID_COLUMNS = 12
MAX_TEXT_TILE_LENGTH = 4000


class DashboardNotFound(Exception):
    """A requested dashboard is not one this team can place an insight on."""


class DashboardNotEditable(Exception):
    """The requester may not change which insights sit on this dashboard."""

    def __init__(self, dashboard_id: int) -> None:
        super().__init__(str(dashboard_id))
        self.dashboard_id = dashboard_id


class DashboardNotViewable(Exception):
    """The requester may not view this dashboard."""


class CannotAddToDashboard(DashboardNotEditable):
    """Raised while placing an insight on a dashboard the requester can only view."""


class CannotRemoveFromDashboard(DashboardNotEditable):
    """Raised while taking an insight off a dashboard the requester can only view."""


@dataclass(frozen=True)
class DashboardRef:
    """A dashboard as insight payloads and activity logs refer to it."""

    id: int
    name: str | None


@dataclass(frozen=True)
class DashboardSummary:
    """One dashboard's own fields, without its tiles."""

    id: int
    team_id: int
    name: str | None
    description: str
    created_at: datetime
    created_by_id: int | None
    deleted: bool
    pinned: bool
    creation_mode: DashboardCreationMode
    last_accessed_at: datetime | None
    last_refresh: datetime | None
    filters: dict[str, Any]
    variables: dict[str, Any] | None

    @property
    def access_ref(self) -> ObjectAccessRef:
        """What object-level access control reads from this dashboard, for `check_access_level_for_ref`."""
        return ObjectAccessRef(
            resource="dashboard", id=str(self.id), team_id=self.team_id, created_by_id=self.created_by_id
        )


@dataclass(frozen=True)
class DashboardInsightTileSummary:
    """A live tile that places an insight on a dashboard."""

    id: int
    dashboard_id: int
    insight_id: int
    layouts: dict[str, Any]
    filters_overrides: dict[str, Any] | None
    group_key: str | None = None


@dataclass(frozen=True)
class DashboardTileGroupSummary:
    key: str
    title: str
    # Every live tile in the group, of any kind, so `heading` matches the dashboard's own.
    tile_count: int

    @property
    def heading(self) -> str:
        if self.title:
            return self.title
        return f"{self.tile_count} tile" if self.tile_count == 1 else f"{self.tile_count} tiles"


@dataclass(frozen=True)
class PlacedInsightTile:
    """The tile that places an insight on a dashboard."""

    id: int
    dashboard_id: int
    # Whether this call put the insight there, by creating the tile or by restoring a removed one.
    added: bool


@dataclass(frozen=True)
class MembershipChange:
    """What one membership write changed, for the caller's analytics events and activity log."""

    added_dashboard_ids: tuple[int, ...]
    removed_dashboard_ids: tuple[int, ...]
    dashboards: tuple[DashboardRef, ...]


@dataclass(frozen=True)
class DashboardInsightTile:
    insight_short_id: str
    filters_overrides: dict[str, Any] | None


@dataclass(frozen=True)
class DashboardInsights:
    dashboard_id: int
    name: str | None
    filters: dict[str, Any]
    variables: dict[str, Any] | None
    tiles: tuple[DashboardInsightTile, ...]


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
    show_description: bool | None = None


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
    # An unlisted dashboard stays out of the dashboard list, and its insights stay out of the saved insights list.
    # The product that created it opens it by id.
    unlisted: bool = False
    filters: dict[str, Any] | None = None


@frozen
class CreatedDashboard:
    id: int
    insight_count: int
    text_tile_count: int
    # In the order of `NewDashboard.tiles`.
    tile_ids: tuple[int, ...] = ()


@frozen
class DashboardTileSnapshot:
    """One live tile of a dashboard: an insight tile has a query, a text tile has a body."""

    tile_id: int
    layout: TileLayout | None
    name: str = ""
    description: str = ""
    query: dict[str, Any] | None = None
    body: str | None = None
    # None follows the dashboard default, as `NewInsightTile.show_description` does.
    show_description: bool | None = None


class AppliedDashboard(Protocol):
    """The dashboard an insight runs on, as far as running the insight reads it.

    `DashboardSummary` satisfies it, and so does the dashboard row, so code outside this product can
    annotate with it while its own callers still pass rows.
    """

    @property
    def id(self) -> int: ...

    @property
    def filters(self) -> dict[str, Any]: ...

    @property
    def variables(self) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class InsightPlacement:
    """An insight placed on a dashboard by a tile."""

    insight_id: int
    dashboard_id: int


@dataclass(frozen=True)
class TilePlacement:
    """A live tile and the dashboard it sits on. `insight_id` is None for a text, button or widget tile."""

    tile_id: int
    dashboard_id: int
    insight_id: int | None


@dataclass(frozen=True)
class TeamDashboardRef:
    """A dashboard and the team that stores it, for listings that span teams."""

    team_id: int
    id: int
    name: str | None


@dataclass(frozen=True)
class DashboardTemplateDefinition:
    """A dashboard template as code defines it. `tiles` holds the stored template tile JSON."""

    template_name: str
    dashboard_description: str | None = None
    dashboard_filters: dict[str, Any] | None = None
    tiles: list[dict[str, Any]] = field(default_factory=list)
    variables: list[dict[str, Any]] | None = None
    tags: list[str] = field(default_factory=list)
    image_url: str | None = None
    scope: DashboardTemplateScope | None = None
    availability_contexts: list[str] | None = None


# Returned only by facade/testing.py; boundary-crossing data types live in this module.


@dataclass(frozen=True)
class PlantedWidgetTile:
    tile_id: int
    widget_id: UUID


@dataclass(frozen=True)
class InsightTileState:
    tile_id: int
    dashboard_id: int
    insight_id: int
    layouts: dict[str, Any]
    color: str | None
    filters_overrides: dict[str, Any] | None
    deleted: bool


@dataclass(frozen=True)
class DashboardWidgetTile:
    tile_id: int
    widget_type: str
    name: str | None
    config: dict[str, Any]


@dataclass(frozen=True)
class DashboardExtras:
    """The dashboard columns that `DashboardSummary` leaves out."""

    share_token: str | None
    is_shared: bool
    quick_filter_ids: list[str] | None
