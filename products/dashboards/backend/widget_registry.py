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

# Canonical widget types. Must match WIDGET_REGISTRY keys.
EXPECTED_WIDGET_TYPES = frozenset({"error_tracking_list"})

DashboardWidgetType = Literal["error_tracking_list"]
DashboardWidgetTypeInput = Literal["error_tracking_list", "error_tracking"]

WIDGET_TYPE_ALIASES: dict[str, str] = {
    "error_tracking": "error_tracking_list",
}


class WidgetRegistryEntry(TypedDict):
    validate_config: Callable[[dict[str, Any]], dict[str, Any]]
    query_fn: Callable[[Team, dict[str, Any]], dict[str, Any]]
    required_scopes: list[str]
    required_product_access: NotRequired[str | None]


# Per-type validate_config / query_fn / access control. Keys must match EXPECTED_WIDGET_TYPES.
WIDGET_REGISTRY: dict[str, WidgetRegistryEntry] = {
    "error_tracking_list": {
        "validate_config": validate_error_tracking_list_config,
        "query_fn": run_error_tracking_list_widget,
        "required_scopes": ["error_tracking:read"],
        "required_product_access": "error_tracking",
    },
}


def normalize_widget_type(widget_type: str) -> str:
    return WIDGET_TYPE_ALIASES.get(widget_type, widget_type)


def get_widget_registry_entry(widget_type: str) -> WidgetRegistryEntry | None:
    return WIDGET_REGISTRY.get(normalize_widget_type(widget_type))


def validate_widget_config(widget_type: str, config: dict[str, Any]) -> dict[str, Any]:
    entry = get_widget_registry_entry(widget_type)
    if entry is None:
        raise DRFValidationError({"widget_type": f"Unknown widget type: {widget_type}"})
    return entry["validate_config"](config)
