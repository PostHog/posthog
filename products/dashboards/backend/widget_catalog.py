from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from products.dashboards.backend.constants import (
    DEFAULT_WIDGET_LIST_LIMIT,
    MAX_WIDGET_RESULT_LIMIT,
    WIDGET_DATE_FROM_VALUES,
)
from products.dashboards.backend.widgets.error_tracking_list import ERROR_TRACKING_ORDER_BY
from products.dashboards.backend.widgets.session_replay_list import SESSION_REPLAY_ORDER_BY
from products.dashboards.backend.widgets.widget_filters import WIDGET_FILTERS_CATALOG_HINT

_ERROR_TRACKING_WIDGET_QUICK_FILTER_NAMES = [
    "Team",
    "Environment",
    "URL path",
    "Temporal worker",
]


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
                "default": DEFAULT_WIDGET_LIST_LIMIT,
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
                "choices": ["active", "resolved", "suppressed", "all"],
                "default": "active",
            },
            "assignee": {
                "type": "object",
                "optional": True,
                "description": "Filter by assignee ({type: user|role, id}). Omit for any assignee.",
            },
            "widgetFilters": {
                **WIDGET_FILTERS_CATALOG_HINT,
                "allowed_filter_names": _ERROR_TRACKING_WIDGET_QUICK_FILTER_NAMES,
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
    "session_replay_list": {
        "widget_type": "session_replay_list",
        "group_id": "session_replay",
        "group_label": "Session replay",
        "label": "Recent recordings",
        "description": "Recent session recordings you can open in the replay player.",
        "config_schema_hints": {
            "limit": {
                "type": "integer",
                "min": 1,
                "max": MAX_WIDGET_RESULT_LIMIT,
                "default": DEFAULT_WIDGET_LIST_LIMIT,
            },
            "orderBy": {
                "type": "string",
                "choices": sorted(SESSION_REPLAY_ORDER_BY),
                "default": "start_time",
            },
            "orderDirection": {
                "type": "string",
                "choices": ["ASC", "DESC"],
                "default": "DESC",
            },
            "dateRange": {
                "date_from": {
                    "type": "string",
                    "choices": sorted(WIDGET_DATE_FROM_VALUES),
                    "optional": True,
                },
            },
            "widgetFilters": {
                **WIDGET_FILTERS_CATALOG_HINT,
                "quick_filter_context": "dashboards",
                "description": (
                    "Event property filters from dashboard filter definitions. "
                    "Configure filters on the dashboard filter bar first."
                ),
            },
            "filterTestAccounts": {
                "type": "boolean",
                "optional": True,
                "uses_project_default": True,
            },
        },
        "required_product_access": "session_recording",
        "product_access_denied_message": "You do not have access to session replay.",
        "availability_requirements": ["session_replay_enabled"],
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
    entry = WIDGET_CATALOG.get(widget_type)
    width = 6
    height = 5
    if entry is not None:
        # Catalog entries may gain default_layout later; keep a stable fallback.
        _ = entry
    return {
        "sm": {"x": 0, "y": 0, "w": width, "h": height},
        "xs": {"x": 0, "y": 0, "w": width, "h": height},
    }
