from __future__ import annotations

from typing import Any

from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.models.team import Team

MAX_WIDGET_CONFIG_LIMIT = 25

WIDGET_DATE_FROM_VALUES = frozenset({"-1h", "-3h", "-24h", "-7d", "-14d", "-30d", "-90d"})


def default_filter_test_accounts_for_team(team: Team) -> bool:
    return bool(team.test_account_filters_default_checked)


def validate_filter_test_accounts_value(value: object) -> bool:
    if not isinstance(value, bool):
        raise DRFValidationError({"config": "filterTestAccounts must be a boolean."})
    return value


def resolve_filter_test_accounts(config: dict[str, Any], team: Team) -> bool:
    """Return whether widget queries should apply team.test_account_filters."""
    if "filterTestAccounts" in config:
        return validate_filter_test_accounts_value(config["filterTestAccounts"])
    return default_filter_test_accounts_for_team(team)


def merge_base_widget_config_fields(config: dict[str, Any]) -> dict[str, Any]:
    """Shared config fields inherited by all widget types."""
    if "filterTestAccounts" not in config:
        return {}
    return {
        "filterTestAccounts": validate_filter_test_accounts_value(config["filterTestAccounts"]),
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
