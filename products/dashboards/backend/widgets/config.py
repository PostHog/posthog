from __future__ import annotations

from typing import Any

from rest_framework.exceptions import ValidationError as DRFValidationError

# Dashboard widgets default to excluding internal/test users (same as weekly digest and
# error-tracking widget historical behavior). Product scenes may use different defaults.
DEFAULT_FILTER_TEST_ACCOUNTS = True

MAX_WIDGET_CONFIG_LIMIT = 25

WIDGET_DATE_FROM_VALUES = frozenset({"-1h", "-3h", "-24h", "-7d", "-14d", "-30d", "-90d"})


def validate_filter_test_accounts(config: dict[str, Any]) -> bool:
    value = config.get("filterTestAccounts", DEFAULT_FILTER_TEST_ACCOUNTS)
    if not isinstance(value, bool):
        raise DRFValidationError({"config": "filterTestAccounts must be a boolean."})
    return value


def resolve_filter_test_accounts(config: dict[str, Any]) -> bool:
    """Return whether widget queries should apply team.test_account_filters."""
    return validate_filter_test_accounts(config)


def merge_base_widget_config_fields(config: dict[str, Any]) -> dict[str, Any]:
    """Shared config fields inherited by all widget types."""
    return {
        "filterTestAccounts": validate_filter_test_accounts(config),
    }


def validate_widget_date_range(date_range: object) -> dict[str, object] | None:
    if date_range is None:
        return None
    if not isinstance(date_range, dict):
        raise DRFValidationError({"config": "dateRange must be an object."})

    date_from = date_range.get("date_from")
    if date_from is not None and (not isinstance(date_from, str) or date_from not in WIDGET_DATE_FROM_VALUES):
        allowed = ", ".join(sorted(WIDGET_DATE_FROM_VALUES))
        raise DRFValidationError({"config": f"dateRange.date_from must be one of: {allowed}."})

    return {str(key): value for key, value in date_range.items()}
