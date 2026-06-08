"""Runtime registry for dashboard widget types.

Maps each widget_type string to the backend hooks that power dashboard tiles:
config validation, query execution, and product access requirements. The
dashboard API uses this when creating/updating widget tiles, enforcing access
on run_widgets, and validating stored config.

Widget metadata shown in the UI and MCP (labels, descriptions, config hints)
lives in widget_catalog.py instead — keep that in sync when adding types here.

New widget types: add an entry to WIDGET_REGISTRY and EXPECTED_WIDGET_TYPES.
See products/dashboards/CONTRIBUTING.md.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, NotRequired, TypedDict

from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.models.team import Team

from products.dashboards.backend.widgets.error_tracking_list import (
    run_error_tracking_list_widget,
    validate_error_tracking_list_config,
)
from products.dashboards.backend.widgets.session_replay_list import (
    run_session_replay_list_widget,
    validate_session_replay_list_config,
)

# Canonical widget type identifiers. Must match WIDGET_REGISTRY keys.
ERROR_TRACKING_LIST_WIDGET_TYPE = "error_tracking_list"
SESSION_REPLAY_LIST_WIDGET_TYPE = "session_replay_list"

EXPECTED_WIDGET_TYPES = frozenset({ERROR_TRACKING_LIST_WIDGET_TYPE, SESSION_REPLAY_LIST_WIDGET_TYPE})

DashboardWidgetType = Literal["error_tracking_list", "session_replay_list"]


class WidgetRegistryEntry(TypedDict):
    validate_config: Callable[[dict[str, Any]], dict[str, Any]]
    query_fn: Callable[[Team, dict[str, Any]], dict[str, Any]]
    required_scopes: list[str]
    required_product_access: NotRequired[str | None]


# Per-type validate_config / query_fn / access control. Keys must match EXPECTED_WIDGET_TYPES.
WIDGET_REGISTRY: dict[str, WidgetRegistryEntry] = {
    ERROR_TRACKING_LIST_WIDGET_TYPE: {
        "validate_config": validate_error_tracking_list_config,
        "query_fn": run_error_tracking_list_widget,
        "required_scopes": ["error_tracking:read"],
        "required_product_access": "error_tracking",
    },
    SESSION_REPLAY_LIST_WIDGET_TYPE: {
        "validate_config": validate_session_replay_list_config,
        "query_fn": run_session_replay_list_widget,
        "required_scopes": ["session_recording:read"],
        "required_product_access": "session_recording",
    },
}


def get_widget_registry_entry(widget_type: str) -> WidgetRegistryEntry | None:
    return WIDGET_REGISTRY.get(widget_type)


def validate_widget_config(widget_type: str, config: dict[str, Any]) -> dict[str, Any]:
    entry = get_widget_registry_entry(widget_type)
    if entry is None:
        raise DRFValidationError({"widget_type": f"Unknown widget type: {widget_type}"})
    return entry["validate_config"](config)
