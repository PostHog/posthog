from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, NotRequired, TypedDict

from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.models.team import Team

from products.dashboards.backend.widgets.config import MAX_WIDGET_CONFIG_LIMIT
from products.dashboards.backend.widgets.error_tracking_list import (
    run_error_tracking_list_widget,
    validate_error_tracking_list_config,
)

# New widget types: add here. See products/dashboards/CONTRIBUTING.md.


WIDGET_TYPE_ALIASES: dict[str, str] = {
    "error_tracking": "error_tracking_list",
}


class WidgetRegistryEntry(TypedDict):
    validate_config: Callable[[dict[str, Any]], dict[str, Any]]
    query_fn: Callable[[Team, dict[str, Any]], dict[str, Any]]
    required_scopes: list[str]
    required_product_access: NotRequired[str | None]


# New widget types: add here. See products/dashboards/CONTRIBUTING.md.
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
