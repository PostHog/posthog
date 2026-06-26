"""Bulk sync of materialized-view columns into account custom property values.

Reads a configured view via HogQL, matches each row to an account by external_id, and writes the
selected column as that account's custom property value (through set_custom_property_value).
Persisting the outcome and auto-disabling sources is the caller's (facade/Temporal) concern.
Called by facade/api.py.
"""

import dataclasses
from typing import Any
from uuid import UUID

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team

from products.customer_analytics.backend.logic.custom_property_values import (
    CustomPropertyValueConflict,
    InvalidCustomPropertyValue,
    set_custom_property_value,
)
from products.customer_analytics.backend.models import Account, CustomPropertySource

_WRITE_CONFLICT_RETRIES = 3


@dataclasses.dataclass
class SyncResult:
    view_found: bool
    written: int = 0
    unmatched_keys: int = 0
    source_errors: dict[str, str] = dataclasses.field(default_factory=dict)


def sync_custom_property_values(*, team_id: int, saved_query_id: str | UUID) -> SyncResult:
    sources = list(
        CustomPropertySource.objects.for_team(team_id)
        .filter(saved_query_id=saved_query_id, is_enabled=True)
        .select_related("definition", "saved_query")
    )
    if not sources:
        return SyncResult(view_found=True)

    saved_query = sources[0].saved_query  # every source for this view points at the same one
    if saved_query is None or saved_query.deleted:
        return SyncResult(view_found=False)

    available_columns = set((saved_query.columns or {}).keys())
    result = SyncResult(view_found=True)
    usable: list[CustomPropertySource] = []
    selected_columns: set[str] = set()
    for source in sources:
        missing = [column for column in (source.key_column, source.source_column) if column not in available_columns]
        if missing:
            result.source_errors[str(source.id)] = f"View {saved_query.name} has no column(s): {', '.join(missing)}"
            continue
        usable.append(source)
        selected_columns.update((source.key_column, source.source_column))
    if not usable:
        return result

    ordered = sorted(selected_columns)
    column_index = {column: position for position, column in enumerate(ordered)}
    rows = _read_view(Team.objects.get(id=team_id), saved_query.name, ordered)
    accounts = _accounts_by_external_id(team_id, rows, column_index, usable)

    unmatched: set[Any] = set()
    for source in usable:
        key_index, value_index = column_index[source.key_column], column_index[source.source_column]
        for row in rows:
            key = row[key_index]
            account = accounts.get(str(key)) if key is not None else None
            if account is None:
                unmatched.add(key)
                continue
            if row[value_index] is None:
                continue
            if _write(team_id=team_id, account_id=account.id, source=source, value=row[value_index], result=result):
                result.written += 1
    result.unmatched_keys = len(unmatched)
    return result


def _accounts_by_external_id(
    team_id: int, rows: list, column_index: dict[str, int], sources: list[CustomPropertySource]
) -> dict[str | None, Account]:
    keys = {row[column_index[source.key_column]] for source in sources for row in rows}
    external_ids = [str(key) for key in keys if key is not None]
    return {a.external_id: a for a in Account.objects.for_team(team_id).filter(external_id__in=external_ids)}


def _write(*, team_id: int, account_id: Any, source: CustomPropertySource, value: Any, result: SyncResult) -> bool:
    for _ in range(_WRITE_CONFLICT_RETRIES):
        try:
            set_custom_property_value(
                team_id=team_id, account_id=account_id, definition_id=source.definition_id, value=value
            )
            return True
        except CustomPropertyValueConflict:
            continue  # transient active-value race — the retry soft-deletes the winner's row first
        except InvalidCustomPropertyValue as exc:
            result.source_errors[str(source.id)] = str(exc)
            return False
    return False  # retries exhausted on a transient conflict; the value updates next run


def _read_view(team: Team, view_name: str, columns: list[str]) -> list:
    query = ast.SelectQuery(
        select=[ast.Field(chain=[column]) for column in columns],
        select_from=ast.JoinExpr(table=ast.Field(chain=[view_name])),
    )
    return execute_hogql_query(query, team=team).results or []
