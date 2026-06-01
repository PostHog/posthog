from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from products.dashboards.backend.widget_registry import normalize_widget_type
from products.dashboards.backend.widgets.config import MAX_WIDGET_RESULT_LIMIT, WIDGET_DATE_FROM_VALUES
from products.dashboards.backend.widgets.error_tracking_list import ERROR_TRACKING_ORDER_BY


class WidgetCatalogEntry(TypedDict):
    widget_type: str
    group_id: str
    group_label: str
    label: str
    description: str
    config_schema_hints: dict[str, Any]
    required_product_access: str | None
    product_access_denied_message: NotRequired[str | None]
    availability_requirements: list[str]


# New widget types: add here. See products/dashboards/CONTRIBUTING.md.
WIDGET_CATALOG: dict[str, WidgetCatalogEntry] = {
    "error_tracking_list": {
        "widget_type": "error_tracking_list",
        "group_id": "error_tracking",
        "group_label": "Error tracking",
        "label": "Top issues",
        "description": "Ranked list of the most impactful error tracking issues.",
        "config_schema_hints": {
            "limit": {
                "type": "integer",
                "min": 1,
                "max": MAX_WIDGET_RESULT_LIMIT,
                "default": 10,
            },
            "orderBy": {
                "type": "string",
                "choices": sorted(ERROR_TRACKING_ORDER_BY),
                "default": "occurrences",
            },
            "orderDirection": {
                "type": "string",
                "choices": ["ASC", "DESC"],
                "default": "DESC",
            },
            "status": {
                "type": "string",
                "choices": ["archived", "active", "resolved", "pending_release", "suppressed", "all"],
                "default": "active",
            },
            "dateRange": {
                "date_from": {
                    "type": "string",
                    "choices": sorted(WIDGET_DATE_FROM_VALUES),
                    "optional": True,
                },
            },
            "filterTestAccounts": {
                "type": "boolean",
                "optional": True,
                "uses_project_default": True,
            },
        },
        "required_product_access": "error_tracking",
        "product_access_denied_message": "You do not have access to error tracking.",
        "availability_requirements": ["exception_autocapture"],
    },
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
    entry = WIDGET_CATALOG.get(normalize_widget_type(widget_type))
    width = 6
    height = 5
    if entry is not None:
        # Catalog entries may gain default_layout later; keep a stable fallback.
        _ = entry
    return {
        "sm": {"x": 0, "y": 0, "w": width, "h": height},
        "xs": {"x": 0, "y": 0, "w": width, "h": height},
    }
