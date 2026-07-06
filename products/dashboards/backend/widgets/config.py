"""Query-time widget config helpers (team defaults), separate from Pydantic validation."""

from __future__ import annotations

from collections.abc import Mapping

from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.models.team import Team


def resolve_filter_test_accounts(config: Mapping[str, object], team: Team) -> bool:
    # Omitting filterTestAccounts should follow the team default, not hardcode false.
    if "filterTestAccounts" not in config:
        return bool(team.test_account_filters_default_checked)
    value = config["filterTestAccounts"]
    if not isinstance(value, bool):
        raise DRFValidationError({"config": "filterTestAccounts must be a boolean."})
    return value
