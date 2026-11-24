"""
Shared enums and constants for the dashboards product.

``DashboardAccessMethod`` labels how a dashboard render was reached. It lives in the facade
rather than in ``backend/access.py`` because the insight API tags its own cache metrics with
it, and a data type that crosses the product boundary belongs here.

The layout and tile group choices, defaults and limits back the dashboard models, the
customization rules and the API serializers in presentation, so they are defined here once.
"""

from enum import StrEnum

from posthog.enums import LabeledStrEnum

from products.dashboards.backend.constants import (
    DASHBOARD_GRID_COLUMN_COUNT,
    MAX_GROUP_KEY_LENGTH,
    MAX_GROUP_TITLE_LENGTH,
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


# A plain StrEnum, not a LabeledStrEnum: only the stored values cross the boundary, and the OpenAPI
# build names a component after every labeled enum it finds.
class DashboardTemplateScope(StrEnum):
    """Who can use a dashboard template. Mirrors `DashboardTemplate.Scope`."""

    ONLY_TEAM = "team"
    ORGANIZATION = "organization"
    GLOBAL = "global"
    FEATURE_FLAG = "feature_flag"


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


__all__ = [
    "DASHBOARD_GRID_COLUMN_COUNT",
    "DASHBOARD_GRID_COMPACTION_MODES",
    "DASHBOARD_GRID_SPACING_GAPS",
    "DASHBOARD_TILE_GROUP_DEFAULTS",
    "DASHBOARD_TILE_GROUP_DISPLAY_MODES",
    "MAX_GROUP_KEY_LENGTH",
    "MAX_GROUP_TITLE_LENGTH",
    "DashboardAccessMethod",
    "DashboardCreationMode",
    "DashboardTemplateScope",
    "DashboardTileBadge",
    "DashboardTileGroupColor",
    "DashboardUsageCount",
    "LayoutCompaction",
    "TileGroupDisplay",
    "TileSpacing",
]
