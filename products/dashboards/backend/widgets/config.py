"""Shared helpers for dashboard widget config: validation, defaults, and common fields."""

from __future__ import annotations

from typing import Any

from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.models.team import Team

from products.dashboards.backend.constants import WIDGET_DATE_FROM_VALUES


def validate_filter_test_accounts_value(value: object) -> bool:
    if not isinstance(value, bool):
        raise DRFValidationError({"config": "filterTestAccounts must be a boolean."})
    return value


def resolve_filter_test_accounts(config: dict[str, Any], team: Team) -> bool:
    # Omitting filterTestAccounts should follow the team default, not hardcode false.
    if "filterTestAccounts" in config:
        return validate_filter_test_accounts_value(config["filterTestAccounts"])
    return bool(team.test_account_filters_default_checked)


def merge_base_widget_config_fields(config: dict[str, Any]) -> dict[str, Any]:
    # Centralizes shared fields so each widget type doesn't re-validate them.
    if "filterTestAccounts" not in config:
        return {}
    return {
        "filterTestAccounts": validate_filter_test_accounts_value(config["filterTestAccounts"]),
    }


def validate_widget_date_range(date_range: object) -> dict[str, object] | None:
    # Fail fast on unsupported shapes before widget runners build queries.
    if date_range is None:
        return None
    if not isinstance(date_range, dict):
        raise DRFValidationError({"config": "dateRange must be an object."})

    date_from = date_range.get("date_from")
    if date_from is not None and (not isinstance(date_from, str) or date_from not in WIDGET_DATE_FROM_VALUES):
        allowed = ", ".join(sorted(WIDGET_DATE_FROM_VALUES))
        raise DRFValidationError({"config": f"dateRange.date_from must be one of: {allowed}."})

    return {"date_from": date_from} if date_from is not None else None
