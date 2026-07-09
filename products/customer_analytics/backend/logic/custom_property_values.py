"""
Business logic for per-account custom property values.

ORM queries, type validation/coercion, the soft-delete + insert transaction, append-only history.
Called by facade/api.py. Do not call from outside this module.
"""

import math
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from products.customer_analytics.backend.models import (
    Account,
    CustomPropertyDefinition,
    CustomPropertyValue,
    DataType,
    DisplayType,
)
from products.customer_analytics.backend.models.custom_property_value import ACTIVE_VALUE_CONSTRAINT_NAME

CoercedValue = float | bool | str | datetime


class InvalidCustomPropertyValue(ValueError):
    """Raised when a value can't be coerced to its definition's data type.

    ``field`` carries the definition id when set from a batch write, so the caller can
    point at which property failed.
    """

    field: str | None = None


class CustomPropertyDefinitionNotFound(Exception):
    """Raised when the target custom property definition does not exist for the team.

    ``identifier`` is the id or name that failed to resolve, so callers can surface which
    property was at fault.
    """

    def __init__(self, identifier: Any) -> None:
        super().__init__(f"Custom property definition '{identifier}' not found.")
        self.identifier = identifier


class CustomPropertyValueConflict(Exception):
    """Raised when a concurrent write already set an active value for this (account, definition).

    Only the active-value uniqueness race maps to this — retrying succeeds, since the retry
    soft-deletes the now-existing active row before inserting. Any other integrity error is a real
    fault and is left to surface.
    """


def set_custom_property_value(
    *,
    team_id: int,
    account_id: str | UUID,
    definition_id: str | UUID,
    value: Any,
    created_by_id: int | None = None,
) -> CustomPropertyValue:
    """Set an account's value for a custom property, preserving history.

    Coerces `value` to the definition's data type, then atomically soft-deletes the current active
    row (if any) and inserts the new one — keeping at most one active row per (team, account,
    definition) while leaving superseded rows for later analysis.

    Raises `CustomPropertyDefinitionNotFound` (unknown definition), `Account.DoesNotExist`
    (account not in team), `InvalidCustomPropertyValue` (value doesn't match the data type), or
    `CustomPropertyValueConflict` (a concurrent write won the active-value race — retry).
    """
    try:
        definition = CustomPropertyDefinition.objects.for_team(team_id).get(id=definition_id)
    except CustomPropertyDefinition.DoesNotExist as exc:
        raise CustomPropertyDefinitionNotFound(definition_id) from exc
    _assert_account_in_team(team_id=team_id, account_id=account_id)
    return _set_value(
        team_id=team_id, account_id=account_id, definition=definition, value=value, created_by_id=created_by_id
    )


def set_account_custom_properties_by_id(
    *,
    team_id: int,
    account_id: str | UUID,
    properties: dict[str, Any],
    created_by_id: int | None = None,
) -> list[CustomPropertyValue]:
    """Set several of an account's custom property values, addressing each by definition id.

    Resolves each id to its team-scoped definition, then applies the same coerce + soft-delete +
    insert as `set_custom_property_value`. Caller is responsible for wrapping the batch in a
    transaction when all-or-nothing semantics are required.

    Raises `CustomPropertyDefinitionNotFound` (unknown id, carrying the id),
    `InvalidCustomPropertyValue` (value doesn't match the data type, carrying the id in `field`),
    `Account.DoesNotExist`, or `CustomPropertyValueConflict`.
    """
    _assert_account_in_team(team_id=team_id, account_id=account_id)
    rows: list[CustomPropertyValue] = []
    for definition_id, value in properties.items():
        try:
            definition = CustomPropertyDefinition.objects.for_team(team_id).get(id=definition_id)
        except (CustomPropertyDefinition.DoesNotExist, ValidationError) as exc:
            raise CustomPropertyDefinitionNotFound(definition_id) from exc
        try:
            row = _set_value(
                team_id=team_id, account_id=account_id, definition=definition, value=value, created_by_id=created_by_id
            )
        except InvalidCustomPropertyValue as exc:
            exc.field = str(definition_id)
            raise
        rows.append(row)
    return rows


def _set_value(
    *,
    team_id: int,
    account_id: str | UUID,
    definition: CustomPropertyDefinition,
    value: Any,
    created_by_id: int | None,
) -> CustomPropertyValue:
    """Coerce `value` and atomically supersede the account's active row for `definition`."""
    column, coerced = _coerce_to_column(definition, value)
    try:
        with transaction.atomic():
            CustomPropertyValue.objects.for_team(team_id).filter(
                account_id=account_id, definition_id=definition.id, is_deleted=False
            ).update(is_deleted=True)
            row = CustomPropertyValue.objects.for_team(team_id).create(
                team_id=team_id,
                account_id=account_id,
                definition_id=definition.id,
                created_by_id=created_by_id,
                **{column: coerced},
            )
    except IntegrityError as exc:
        if _is_active_value_conflict(exc):
            raise CustomPropertyValueConflict(
                f"An active value for custom property '{definition.name}' was set concurrently."
            ) from exc
        raise
    # Cache the definition we already hold so callers reading row.definition.* don't trigger a
    # lazy FK load against the fail-closed manager (which would raise outside request scope).
    row.definition = definition
    return row


def _is_active_value_conflict(exc: IntegrityError) -> bool:
    return ACTIVE_VALUE_CONSTRAINT_NAME in str(exc)


def list_active_custom_property_values(*, team_id: int, account_id: str | UUID) -> list[CustomPropertyValue]:
    """The account's current (non-deleted) values, newest first."""
    return list(
        CustomPropertyValue.objects.for_team(team_id)
        .filter(account_id=account_id, is_deleted=False)
        .select_related("definition", "created_by")
        .order_by("-created_at")
    )


VALUE_SUGGESTIONS_LIMIT = 50


def list_custom_property_value_suggestions(*, team_id: int, definition_id: str | UUID, search: str | None) -> list[str]:
    """Suggested filter values for a custom property: a select's option labels, a boolean's
    true/false, otherwise distinct active values across the team's accounts. Empty when the
    definition doesn't exist — suggestions are best-effort, not an error surface."""
    try:
        definition = CustomPropertyDefinition.objects.for_team(team_id).get(id=definition_id)
    except (CustomPropertyDefinition.DoesNotExist, ValidationError, ValueError):
        return []

    needle = (search or "").strip().lower()

    if definition.display_type == DisplayType.SELECT:
        labels = [str(option.get("label") or "") for option in definition.options or []]
        return [label for label in labels if label and needle in label.lower()][:VALUE_SUGGESTIONS_LIMIT]
    if definition.data_type == DataType.BOOLEAN:
        return [value for value in ("true", "false") if needle in value]
    if definition.data_type == DataType.DATETIME:
        # Date filters render a date picker, not text suggestions.
        return []

    queryset = CustomPropertyValue.objects.for_team(team_id).filter(definition_id=definition.id, is_deleted=False)

    if definition.data_type == DataType.NUMERIC:
        numeric_values = (
            queryset.exclude(value_num__isnull=True)
            .values_list("value_num", flat=True)
            .distinct()
            .order_by("value_num")
        )
        # The needle matches the *formatted* numeric string, which the database can't compute —
        # filter in Python and stop once the limit fills, instead of slicing the queryset first.
        suggestions: list[str] = []
        for value in numeric_values.iterator():
            formatted = _format_numeric_suggestion(value)
            if formatted is None or needle not in formatted:
                continue
            suggestions.append(formatted)
            if len(suggestions) == VALUE_SUGGESTIONS_LIMIT:
                break
        return suggestions

    if needle:
        queryset = queryset.filter(value_str__icontains=needle)
    return list(
        queryset.exclude(value_str__isnull=True)
        .values_list("value_str", flat=True)
        .distinct()
        .order_by("value_str")[:VALUE_SUGGESTIONS_LIMIT]
    )


def _format_numeric_suggestion(value: float) -> str | None:
    # Integral floats render without a trailing ".0", matching how the filter column displays
    # them. Non-finite values can't pass write-path coercion; skip a stray row rather than crash.
    if not math.isfinite(value):
        return None
    return str(int(value)) if value == int(value) else str(value)


def _assert_account_in_team(*, team_id: int, account_id: str | UUID) -> None:
    if not Account.objects.for_team(team_id).filter(id=account_id).exists():
        raise Account.DoesNotExist(f"Account {account_id} not found for team {team_id}")


def _expects(definition: CustomPropertyDefinition, what: str) -> str:
    return f"Custom property '{definition.name}' expects {what}"


def _coerce_numeric(definition: CustomPropertyDefinition, value: Any) -> float:
    # bool is a subclass of int — reject it so True doesn't silently become 1.0.
    if isinstance(value, bool):
        raise InvalidCustomPropertyValue(_expects(definition, "a numeric value"))
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise InvalidCustomPropertyValue(_expects(definition, "a numeric value"))
    # Reject NaN/inf: float() accepts "nan"/"inf", but a non-finite value silently corrupts
    # AVG/SUM aggregates over this column downstream.
    if not math.isfinite(result):
        raise InvalidCustomPropertyValue(_expects(definition, "a finite numeric value"))
    return result


def _coerce_boolean(definition: CustomPropertyDefinition, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and (normalized := value.strip().lower()) in ("true", "false"):
        return normalized == "true"
    raise InvalidCustomPropertyValue(_expects(definition, "a boolean value"))


def _coerce_datetime(definition: CustomPropertyDefinition, value: Any) -> datetime:
    # datetime must be checked before date — datetime is a subclass of date.
    if isinstance(value, datetime):
        return timezone.make_aware(value, UTC) if timezone.is_naive(value) else value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, str):
        try:
            # fromisoformat accepts both date-only ("2026-01-01", a DisplayType.DATE input) and a
            # trailing "Z", which parse_datetime does not.
            parsed = datetime.fromisoformat(value)
        except ValueError:
            raise InvalidCustomPropertyValue(_expects(definition, "an ISO-8601 datetime"))
        return timezone.make_aware(parsed, UTC) if timezone.is_naive(parsed) else parsed
    raise InvalidCustomPropertyValue(_expects(definition, "an ISO-8601 datetime"))


def _coerce_string(definition: CustomPropertyDefinition, value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    raise InvalidCustomPropertyValue(_expects(definition, "a text value"))


def _coerce_select(definition: CustomPropertyDefinition, value: Any) -> str:
    labels = [option["label"] for option in definition.options or []]
    if isinstance(value, str) and value in labels:
        return value
    raise InvalidCustomPropertyValue(_expects(definition, f"one of its options: {', '.join(labels)}"))


# Each data type maps to its CustomPropertyValue column and the coercer that validates a raw value
# into it (defined here, after the coercers it references).
_HANDLER_BY_DATA_TYPE: dict[DataType, tuple[str, Callable[[CustomPropertyDefinition, Any], CoercedValue]]] = {
    DataType.STRING: ("value_str", _coerce_string),
    DataType.NUMERIC: ("value_num", _coerce_numeric),
    DataType.BOOLEAN: ("value_bool", _coerce_boolean),
    DataType.DATETIME: ("value_datetime", _coerce_datetime),
}


def _coerce_to_column(definition: CustomPropertyDefinition, value: Any) -> tuple[str, CoercedValue]:
    if definition.display_type == DisplayType.SELECT:
        return "value_str", _coerce_select(definition, value)
    column, coerce = _HANDLER_BY_DATA_TYPE[definition.data_type]
    return column, coerce(definition, value)


def value_of(row: CustomPropertyValue) -> CoercedValue | None:
    """The value stored on `row`, read from the column matching its definition's data type."""
    column, _ = _HANDLER_BY_DATA_TYPE[row.definition.data_type]
    return getattr(row, column)
