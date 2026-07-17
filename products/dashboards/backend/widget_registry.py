"""Runtime registry for dashboard widget types.

Maps each widget_type string to the backend hooks that power dashboard tiles.
See products/dashboards/backend/widget_specs/ for config contracts and catalog metadata.
"""

from __future__ import annotations

from products.dashboards.backend.widget_specs.configs import (
    ACTIVITY_EVENTS_LIST_WIDGET_TYPE,
    ERROR_TRACKING_LIST_WIDGET_TYPE,
    EXPERIMENT_RESULTS_WIDGET_TYPE,
    EXPERIMENTS_LIST_WIDGET_TYPE,
    SESSION_REPLAY_LIST_WIDGET_TYPE,
    SURVEY_RESULTS_WIDGET_TYPE,
)
from products.dashboards.backend.widget_specs.registry import (
    EXPECTED_WIDGET_TYPES,
    WIDGET_SPECS,
    DashboardWidgetType,
    WidgetRegistryEntry,
    count_active_widget_filters,
    extract_widget_filters,
    get_widget_registry_entry,
    validate_widget_config,
)

WIDGET_REGISTRY: dict[str, WidgetRegistryEntry] = {
    widget_type: entry
    for widget_type in EXPECTED_WIDGET_TYPES
    if (entry := get_widget_registry_entry(widget_type)) is not None
}

__all__ = [
    "ACTIVITY_EVENTS_LIST_WIDGET_TYPE",
    "ERROR_TRACKING_LIST_WIDGET_TYPE",
    "EXPERIMENT_RESULTS_WIDGET_TYPE",
    "EXPERIMENTS_LIST_WIDGET_TYPE",
    "SESSION_REPLAY_LIST_WIDGET_TYPE",
    "SURVEY_RESULTS_WIDGET_TYPE",
    "EXPECTED_WIDGET_TYPES",
    "DashboardWidgetType",
    "WidgetRegistryEntry",
    "WIDGET_SPECS",
    "WIDGET_REGISTRY",
    "count_active_widget_filters",
    "extract_widget_filters",
    "get_widget_registry_entry",
    "validate_widget_config",
]
