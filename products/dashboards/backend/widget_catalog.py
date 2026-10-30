from __future__ import annotations

from collections.abc import Sequence
from typing import Any, NotRequired, TypedDict

from rest_framework import exceptions

from products.dashboards.backend.widget_specs.registry import WIDGET_SPECS


class WidgetCatalogEntry(TypedDict):
    widget_type: str
    group_id: str
    group_label: str
    label: str
    description: str
    config_schema: dict[str, Any]
    required_product_access: str | None
    product_access_denied_message: NotRequired[str | None]
    availability_requirements: list[str]
    live: bool


def _build_catalog_entry(widget_type: str) -> WidgetCatalogEntry:
    spec = WIDGET_SPECS[widget_type]
    return {
        "widget_type": spec.widget_type,
        "group_id": spec.group_id,
        "group_label": spec.group_label,
        "label": spec.label,
        "description": spec.description,
        "config_schema": spec.config_model.model_json_schema(mode="serialization"),
        "required_product_access": spec.required_product_access,
        "product_access_denied_message": spec.product_access_denied_message,
        "availability_requirements": list(spec.availability_requirements),
        "live": spec.is_live,
    }


WIDGET_CATALOG: dict[str, WidgetCatalogEntry] = {
    widget_type: _build_catalog_entry(widget_type) for widget_type in WIDGET_SPECS
}


def get_widget_catalog_entries(widget_types: Sequence[str] | None = None) -> list[WidgetCatalogEntry]:
    if not widget_types:
        return list(WIDGET_CATALOG.values())
    requested = set(widget_types)
    return [entry for widget_type, entry in WIDGET_CATALOG.items() if widget_type in requested]


def parse_widget_type_filter(raw_values: Sequence[str]) -> list[str]:
    """Parse `widget_type` query values. Each value can hold one type or a comma-separated list."""
    widget_types = list(dict.fromkeys(part.strip() for raw in raw_values for part in raw.split(",") if part.strip()))
    unknown = [widget_type for widget_type in widget_types if widget_type not in WIDGET_CATALOG]
    if unknown:
        raise exceptions.ValidationError(
            {
                "widget_type": f"Unknown widget type: {', '.join(unknown)}. "
                f"Valid types: {', '.join(sorted(WIDGET_CATALOG))}."
            }
        )
    return widget_types


def get_widget_product_access_denied_message(required_product_access: str) -> str:
    for entry in WIDGET_CATALOG.values():
        if entry.get("required_product_access") == required_product_access:
            message = entry.get("product_access_denied_message")
            if message:
                return message
    return f"You do not have access to {required_product_access.replace('_', ' ')}."


def get_default_widget_layouts(widget_type: str) -> dict[str, dict[str, int]]:
    spec = WIDGET_SPECS.get(widget_type)
    width = spec.default_width if spec else 6
    height = spec.default_height if spec else 5
    return {
        "sm": {"x": 0, "y": 0, "w": width, "h": height},
        "xs": {"x": 0, "y": 0, "w": width, "h": height},
    }
