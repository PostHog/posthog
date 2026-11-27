"""
Shared enums and constants for the dashboards product.

``DashboardAccessMethod`` labels how a dashboard render was reached. It lives in the facade
rather than in ``backend/access.py`` because the insight API tags its own cache metrics with
it, and a data type that crosses the product boundary belongs here.

The layout and tile group choices, defaults and limits back the dashboard models, the
customization rules and the API serializers in presentation, so they are defined here once.
The other request limits that the dashboard views enforce are re-exported from
``backend/constants.py``, because presentation reads internals only through the facade.
"""

from enum import StrEnum

from posthog.enums import LabeledStrEnum

from products.dashboards.backend.constants import (
    DASHBOARD_GRID_COLUMN_COUNT,
    MAX_GROUP_KEY_LENGTH,
    MAX_GROUP_TITLE_LENGTH,
    MAX_GROUPS,
    MAX_TEXT_TILE_AGENT_CONTEXT_LENGTH,
    MAX_WIDGETS_BATCH_SIZE,
)


class DashboardAccessMethod(StrEnum):
    HUMAN = "human"
    SHARED = "shared"
    EMBEDDED = "embedded"
    API = "api"


class DashboardCreationMode(LabeledStrEnum):
    """How a dashboard came to exist. Mirrors `Dashboard.CreationMode`."""

    DEFAULT = "default", "Default"
    TEMPLATE = "template", "Template"
    DUPLICATE = "duplicate", "Duplicate"
    UNLISTED = "unlisted", "Unlisted (product-embedded)"


# Keep the labels equal to those of `DashboardTemplate.Scope`. The OpenAPI build names the
# `DashboardTemplateScopeEnum` component after the two classes only while they hold the same choices.
class DashboardTemplateScope(LabeledStrEnum):
    """Who can use a dashboard template. Mirrors `DashboardTemplate.Scope`."""

    ONLY_TEAM = "team", "Only team"
    ORGANIZATION = "organization", "Organization"
    GLOBAL = "global", "Global"
    FEATURE_FLAG = "feature_flag", "Feature Flag"


class DashboardTemplateOrdering(StrEnum):
    """How the template list sorts after featured templates. A search sorts by relevance instead."""

    NAME = "template_name"
    NAME_DESCENDING = "-template_name"
    CREATED_AT = "created_at"
    CREATED_AT_DESCENDING = "-created_at"


class DashboardUsageCount(StrEnum):
    """Which dashboards the usage report counts for each team."""

    ALL = "all"
    FROM_TEMPLATE = "from_template"
    SHARED = "shared"
    TAGGED = "tagged"


DASHBOARD_GRID_SPACING_GAPS: dict[str, int] = {
    "tight": 8,
    "condensed": 12,
    "standard": 16,
    "relaxed": 32,
    "wide": 48,
}


class TileSpacing(LabeledStrEnum):
    TIGHT = "tight", "tight"
    CONDENSED = "condensed", "condensed"
    STANDARD = "standard", "standard"
    RELAXED = "relaxed", "relaxed"
    WIDE = "wide", "wide"


class LayoutCompaction(LabeledStrEnum):
    VERTICAL = "vertical", "vertical"
    HORIZONTAL = "horizontal", "horizontal"
    STABLE = "stable", "stable"


DASHBOARD_GRID_COMPACTION_MODES: tuple[str, ...] = tuple(LayoutCompaction.values)


class TileGroupDisplay(LabeledStrEnum):
    SECTIONS = "sections", "sections"
    TABS = "tabs", "tabs"


DASHBOARD_TILE_GROUP_DISPLAY_MODES: tuple[str, ...] = tuple(TileGroupDisplay.values)


class DashboardTileGroupColor(LabeledStrEnum):
    BLUE = "blue", "Blue"
    PURPLE = "purple", "Purple"
    GREEN = "green", "Green"
    YELLOW = "yellow", "Yellow"
    ORANGE = "orange", "Orange"
    RED = "red", "Red"


DASHBOARD_TILE_GROUP_DEFAULTS: dict[str, bool | None] = {"collapsed": False, "color": None}


class DashboardTileBadge(LabeledStrEnum):
    WINNER = "winner", "Winner"
    CHEEKY_HOG = "cheeky-hog", "Cheeky hog"


class QueryBatchLanguage(LabeledStrEnum):
    """What a query batch target's `query` text holds."""

    QUERY = "query", "Query"
    # Deprecated name for `query`, kept so callers written against it keep working.
    INSIGHT = "insight", "Insight"
    HOGQL = "hogql", "HogQL"
    PROMQL = "promql", "PromQL"
    LOGQL = "logql", "LogQL"


class QueryBatchTargetFormat(LabeledStrEnum):
    """How the client draws a query batch target. Echoed back on its line."""

    TIME_SERIES = "time_series", "Time series"
    TABLE = "table", "Table"


class ResultFormat(LabeledStrEnum):
    """What a cached tile or a query batch line carries: the runner's own result, or frames any chart can draw."""

    RESULT = "result", "Result"
    FRAMES = "frames", "Frames"


class QueryBatchEngine(LabeledStrEnum):
    """Which events engine a query batch target runs on."""

    CLASSIC = "classic", "Classic"
    NEW = "new", "New"


class CachedTileStatus(LabeledStrEnum):
    """What the batched cached-tiles read found for one requested tile."""

    HIT = "hit", "Hit"
    MISS = "miss", "Miss"
    FORBIDDEN = "forbidden", "Forbidden"
    NOT_FOUND = "not_found", "Not found"


class DashboardSharingOutcome(LabeledStrEnum):
    """How one query of a dashboard query stream ran: with another tile's query, alone, or alone after a failed share."""

    SHARED = "shared", "Shared"
    SEPARATE = "separate", "Separate"
    FALLBACK = "fallback", "Shared attempt failed"


__all__ = [
    "DASHBOARD_GRID_COLUMN_COUNT",
    "DASHBOARD_GRID_COMPACTION_MODES",
    "DASHBOARD_GRID_SPACING_GAPS",
    "DASHBOARD_TILE_GROUP_DEFAULTS",
    "DASHBOARD_TILE_GROUP_DISPLAY_MODES",
    "MAX_GROUPS",
    "MAX_GROUP_KEY_LENGTH",
    "MAX_GROUP_TITLE_LENGTH",
    "MAX_TEXT_TILE_AGENT_CONTEXT_LENGTH",
    "MAX_WIDGETS_BATCH_SIZE",
    "CachedTileStatus",
    "DashboardAccessMethod",
    "DashboardCreationMode",
    "DashboardSharingOutcome",
    "DashboardTemplateOrdering",
    "DashboardTemplateScope",
    "DashboardTileBadge",
    "DashboardTileGroupColor",
    "DashboardUsageCount",
    "LayoutCompaction",
    "QueryBatchEngine",
    "QueryBatchLanguage",
    "QueryBatchTargetFormat",
    "TileGroupDisplay",
    "TileSpacing",
]


class BoardManagedBy(LabeledStrEnum):
    """Who writes a `dashboard-v2` board. Only native boards can be changed or deleted through the API."""

    NATIVE = "native", "Native"
    BUILTIN = "builtin", "Built-in"
    IAC = "iac", "Infrastructure as code"
