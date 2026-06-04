"""Shared validation and query bridging for dashboard widget `config.widgetFilters`."""

from __future__ import annotations

from typing import Any

from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.schema import PropertyGroupFilter, PropertyOperator

from posthog.models.quick_filter import QuickFilter

WIDGET_FILTER_OPERATORS = frozenset(operator.value for operator in PropertyOperator)

# Documented in widget_catalog config_schema_hints and OpenAPI widget config serializers.
WIDGET_FILTERS_CATALOG_HINT: dict[str, Any] = {
    "type": "object",
    "optional": True,
    "description": (
        "Widget filter selections keyed by filter id. Each key must match the entry's filterId. "
        "Configure filters in the product UI first, then copy filter id, option id, and property name here."
    ),
    "entry": {
        "filterId": {
            "type": "string",
            "required": True,
            "description": "Filter UUID; must equal the object key.",
        },
        "propertyName": {
            "type": "string",
            "required": True,
            "description": "Event property key applied by this filter (for example $environment).",
        },
        "optionId": {
            "type": "string",
            "required": True,
            "description": "Selected option id from the filter definition.",
        },
        "operator": {
            "type": "string",
            "required": True,
            "description": "Property filter operator (for example exact, is_not, icontains).",
        },
        "value": {
            "type": "string|array|null",
            "optional": True,
            "description": "Filter value as a string, list of strings, or null.",
        },
    },
}


def widget_filters_from_config(config: dict[str, Any]) -> Any:
    """Read widgetFilters from config, falling back to legacy quickFilters."""
    if "widgetFilters" in config:
        return config["widgetFilters"]
    if "quickFilters" in config:
        return config["quickFilters"]
    return None


def validate_widget_filters(config: dict[str, Any]) -> dict[str, dict[str, Any]] | None:
    raw = widget_filters_from_config(config)
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise DRFValidationError({"config": "widgetFilters must be an object."})

    validated: dict[str, dict[str, Any]] = {}
    for filter_id, entry in raw.items():
        if not isinstance(filter_id, str) or not filter_id:
            raise DRFValidationError({"config": "widgetFilters keys must be non-empty strings."})
        if not isinstance(entry, dict):
            raise DRFValidationError({"config": "widgetFilters values must be objects."})
        for required_key in ("filterId", "propertyName", "optionId", "operator"):
            if required_key not in entry:
                raise DRFValidationError({"config": f"widgetFilters.{filter_id} is missing {required_key}."})
        if entry["filterId"] != filter_id:
            raise DRFValidationError({"config": f"widgetFilters.{filter_id} filterId must match the key."})
        property_name = entry["propertyName"]
        if not isinstance(property_name, str) or not property_name:
            raise DRFValidationError({"config": f"widgetFilters.{filter_id} propertyName must be a non-empty string."})
        option_id = entry["optionId"]
        if not isinstance(option_id, str) or not option_id:
            raise DRFValidationError({"config": f"widgetFilters.{filter_id} optionId must be a non-empty string."})
        operator = entry["operator"]
        if not isinstance(operator, str) or not operator:
            raise DRFValidationError({"config": f"widgetFilters.{filter_id} operator must be a non-empty string."})
        if operator not in WIDGET_FILTER_OPERATORS:
            raise DRFValidationError({"config": f"widgetFilters.{filter_id} operator {operator!r} is not supported."})
        value = entry.get("value")
        if value is not None and not isinstance(value, str | list):
            raise DRFValidationError({"config": f"widgetFilters.{filter_id} value must be a string, list, or null."})
        if isinstance(value, list) and not all(isinstance(item, str) for item in value):
            raise DRFValidationError({"config": f"widgetFilters.{filter_id} value list items must be strings."})
        validated[filter_id] = {
            "filterId": filter_id,
            "propertyName": property_name,
            "optionId": option_id,
            "operator": operator,
            "value": value,
        }
    return validated or None


# Keep in sync with ERROR_TRACKING_WIDGET_QUICK_FILTER_PROPERTY_NAMES in
# products/dashboards/frontend/widgets/error_tracking/constants.ts
ERROR_TRACKING_WIDGET_FILTER_PROPERTY_NAMES = frozenset(
    {
        "$environment",
        "$current_url",
        "$pathname",
        "$team",
        "$posthog_team",
        "$temporal_worker",
        "$temporal_worker_name",
    }
)


def _quick_filter_property_names_by_id(team_id: int, allowed_quick_filter_ids: list[str]) -> dict[str, str]:
    if not allowed_quick_filter_ids:
        return {}
    filters = QuickFilter.objects.filter(team_id=team_id, id__in=allowed_quick_filter_ids).values("id", "property_name")
    return {str(row["id"]): str(row["property_name"]) for row in filters}


def filter_session_replay_widget_filters_for_dashboard(
    validated: dict[str, dict[str, Any]],
    *,
    team_id: int,
    allowed_quick_filter_ids: list[str],
) -> dict[str, dict[str, Any]]:
    allowed_ids = {str(filter_id) for filter_id in allowed_quick_filter_ids}
    property_names_by_id = _quick_filter_property_names_by_id(team_id, list(allowed_ids))
    filtered: dict[str, dict[str, Any]] = {}
    for filter_id, entry in validated.items():
        if filter_id not in allowed_ids:
            continue
        expected_property_name = property_names_by_id.get(filter_id)
        if expected_property_name is None:
            continue
        if entry["propertyName"].strip().lower() != expected_property_name.strip().lower():
            continue
        filtered[filter_id] = entry
    return filtered


def validate_session_replay_widget_filters(
    config: dict[str, Any],
    *,
    team_id: int,
    allowed_quick_filter_ids: list[str],
) -> dict[str, dict[str, Any]] | None:
    """Restrict SR widget filters to dashboard quick filters and their property names."""
    validated = validate_widget_filters(config)
    if validated is None:
        return None

    filtered = filter_session_replay_widget_filters_for_dashboard(
        validated,
        team_id=team_id,
        allowed_quick_filter_ids=allowed_quick_filter_ids,
    )
    if len(filtered) != len(validated):
        rejected = set(validated.keys()) - set(filtered.keys())
        filter_id = next(iter(rejected))
        raise DRFValidationError(
            {
                "config": (
                    f"widgetFilters.{filter_id} is not allowed on this dashboard. "
                    "Use a filter from the dashboard quick filter bar."
                )
            }
        )
    return filtered or None


def validate_error_tracking_widget_filters(config: dict[str, Any]) -> dict[str, dict[str, Any]] | None:
    validated = validate_widget_filters(config)
    if validated is None:
        return None

    for filter_id, entry in validated.items():
        property_name = entry["propertyName"].strip().lower()
        if property_name not in ERROR_TRACKING_WIDGET_FILTER_PROPERTY_NAMES:
            raise DRFValidationError(
                {
                    "config": (
                        f"widgetFilters.{filter_id} uses unsupported property "
                        f"{entry['propertyName']!r} for error tracking widgets."
                    )
                }
            )
    return validated


def _event_property_filters_from_widget_filters(
    widget_filters: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    property_filters: list[dict[str, Any]] = []
    for entry in widget_filters.values():
        filter_value = entry.get("value")
        property_filter: dict[str, Any] = {
            "type": "event",
            "key": entry["propertyName"],
            "operator": entry["operator"],
        }
        if filter_value is not None:
            property_filter["value"] = filter_value if isinstance(filter_value, list) else [filter_value]
        property_filters.append(property_filter)
    return property_filters


def build_event_property_filters_from_widget_filters(
    widget_filters: dict[str, dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    if not widget_filters:
        return None
    property_filters = _event_property_filters_from_widget_filters(widget_filters)
    return property_filters or None


def build_property_group_filter_from_widget_filters(
    widget_filters: dict[str, dict[str, Any]] | None,
) -> PropertyGroupFilter | None:
    if not widget_filters:
        return None

    property_filters = _event_property_filters_from_widget_filters(widget_filters)
    if not property_filters:
        return None

    return PropertyGroupFilter.model_validate(
        {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": property_filters,
                }
            ],
        }
    )
