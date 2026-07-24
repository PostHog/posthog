from __future__ import annotations

from typing import Any, NotRequired, TypedDict

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
    }


WIDGET_CATALOG: dict[str, WidgetCatalogEntry] = {
    widget_type: _build_catalog_entry(widget_type) for widget_type in WIDGET_SPECS
}


def get_widget_catalog_entries() -> list[WidgetCatalogEntry]:
    return list(WIDGET_CATALOG.values())


def get_widget_product_access_denied_message(required_product_access: str) -> str:
    for entry in WIDGET_CATALOG.values():
        if entry.get("required_product_access") == required_product_access:
            message = entry.get("product_access_denied_message")
            if message:
                return message
    return f"You do not have access to {required_product_access.replace('_', ' ')}."


def get_default_widget_layouts(widget_type: str) -> dict[str, dict[str, int]]:
    width = 6
    height = 5
    return {
        "sm": {"x": 0, "y": 0, "w": width, "h": height},
        "xs": {"x": 0, "y": 0, "w": width, "h": height},
    }
