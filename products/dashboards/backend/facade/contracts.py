"""
Contract types for dashboards.

Frozen dataclasses, errors and the `AppliedDashboard` protocol that cross the dashboards boundary.
No Django imports: the facade maps dashboard and tile rows to these, and callers outside the
product hold only these.
"""

from collections.abc import Sequence
from dataclasses import field
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import JsonValue
from pydantic.dataclasses import dataclass

from posthog.dataclasses import frozen

from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.dashboards.backend.facade.enums import (
    DashboardCreationMode,
    DashboardTemplateOrdering,
    DashboardTemplateScope,
    QueryBatchEngine,
    QueryBatchLanguage,
    QueryBatchTargetFormat,
)

GRID_COLUMNS = 12
MAX_TEXT_TILE_LENGTH = 4000


class DashboardNotFound(Exception):
    """A requested dashboard is not one this team can place an insight on."""


class QueryBatchBusy(Exception):
    """Too many query batches are reading or running for this process or team to take another one now."""


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


MAX_DASHBOARD_TEMPLATES_PER_ORGANIZATION = 100


class DashboardTemplateNotFound(LookupError):
    """No template this project can see has this id. The API answers 404."""


class DashboardTemplateWriteRejected(ValueError):
    """A template write breaks a rule. The API answers 400 with `message`, on `field` when it names one."""

    def __init__(self, message: str, *, field: str | None = None, code: str = "invalid") -> None:
        super().__init__(message)
        self.message = message
        self.field = field
        self.code = code


@dataclass(frozen=True)
class DashboardTemplateCreator:
    """The user fields a template response shows for its creator."""

    id: int
    uuid: UUID
    distinct_id: str | None
    first_name: str
    last_name: str
    email: str
    is_email_verified: bool | None
    hedgehog_config: dict[str, Any] | None
    role_at_organization: str | None


@dataclass(frozen=True)
class DashboardTemplate:
    """A stored dashboard template. The JSON columns hold whatever JSON the API accepted for them."""

    id: UUID
    team_id: int | None
    template_name: str | None
    dashboard_description: str | None
    dashboard_filters: JsonValue
    tiles: JsonValue
    variables: JsonValue
    customization: JsonValue
    tags: list[str] | None
    created_at: datetime | None
    created_by_id: int | None
    created_by: DashboardTemplateCreator | None
    deleted: bool | None
    image_url: str | None
    # The stored value. A staff update can store a blank scope, and nothing in the database holds a row to the
    # choices, so a value outside them reads back as the raw string instead of failing the read.
    scope: DashboardTemplateScope | str | None
    availability_contexts: list[str] | None
    is_featured: bool


@dataclass(frozen=True)
class DashboardTemplateWrite:
    """The template fields a create or an update writes. Only the fields named in `fields_set` are written."""

    fields_set: frozenset[str]
    template_name: str | None = None
    dashboard_description: str | None = None
    dashboard_filters: JsonValue = None
    tags: list[str] | None = None
    tiles: JsonValue = None
    variables: JsonValue = None
    customization: JsonValue = None
    deleted: bool | None = None
    image_url: str | None = None
    scope: DashboardTemplateScope | Literal[""] | None = None
    availability_contexts: list[str] | None = None
    is_featured: bool = False


@dataclass(frozen=True)
class DashboardTemplateFilters:
    """The list query params. They narrow a retrieve or an update too."""

    scope: DashboardTemplateScope | None = None
    # An empty search still filters by rank. Only None leaves the list unsearched.
    search: str | None = None
    ordering: DashboardTemplateOrdering | None = None
    is_featured: bool | None = None


@dataclass(frozen=True)
class NonPortableReferences:
    """Project-specific references in a template's tiles, which another project may not have."""

    actions: int
    cohorts: int
    warehouse_tables: tuple[str, ...]


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


# Cached tiles draw time and number fields. A query batch table also has string, boolean and other columns.
FrameFieldType = Literal["time", "number", "string", "boolean", "other"]


@frozen
class FrameField:
    """One column of a frame: the time of each point, or its values."""

    name: str
    type: FrameFieldType
    # A time field holds epoch milliseconds. A number field holds null for a gap.
    values: Sequence[JsonValue]
    unit: str | None = None
    # The series' labels, on each value field of a pivoted table.
    labels: dict[str, str] | None = None


@frozen
class FrameMeta:
    """What a frame covers: its bucket size and date range."""

    # PostHog's interval name: second_15 to week for metrics, minute to month for trends.
    interval: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    # The same series over the compared period, with that period's dates.
    previous: bool = False
    # The table had more rows than were returned, so the frame is cut.
    truncated: bool = False


@frozen
class Frame:
    """One chart-ready series, the contract between a tile's query and its chart (Dash's `DataFrame`)."""

    # None for a table frame, which has no series name.
    name: str | None
    labels: dict[str, str]
    fields: list[FrameField]
    meta: FrameMeta


@frozen
class QueryBatchTarget:
    """A panel's query. For `query`, `query` is a PostHog query node as JSON, bare or as
    `{query: <query node>, filters?, variables?}`. For `hogql`, it is the SQL, which reads the batch's time range
    through `{filters}`. For `promql` and `logql`, it is the expression, run as a range query over the batch's time
    range. `legend` and `format` are the client's and come back unchanged on the target's line."""

    ref_id: str
    language: QueryBatchLanguage
    query: str
    legend: str | None = None
    format: QueryBatchTargetFormat | None = None
    engine: QueryBatchEngine | None = None


@frozen
class QueryBatchInput:
    """One query of a batch. `date_from` and `date_to` are expressions like `now-7d` and `now`."""

    target: QueryBatchTarget
    date_from: str
    date_to: str
    variables: dict[str, Any] | None = None
    interval: str | None = None
    swr: bool = False
    cache_only: bool = False
    max_data_points: int | None = None
    tile: str | None = None
