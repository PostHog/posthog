"""Bulk sync of materialized-view columns into account custom property values.

Reads a configured view via HogQL, matches each row to an account by external_id, and writes the
selected column as that account's custom property value (through set_custom_property_value).
`run_custom_property_sync` is the entrypoint the Celery task calls: it runs the sync and persists
the outcome (success/failure, auto-disable) onto the sources.
"""

import dataclasses
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.exceptions_capture import capture_exception
from posthog.models import Team

from products.customer_analytics.backend.logic.custom_property_values import (
    CustomPropertyValueConflict,
    InvalidCustomPropertyValue,
    set_custom_property_value,
)
from products.customer_analytics.backend.models import Account, CustomPropertySource

_WRITE_CONFLICT_RETRIES = 3

# Mirrors data_modeling's CONSECUTIVE_TIMEOUTS_TO_PAUSE: auto-disable a source that keeps failing.
MAX_CONSECUTIVE_SYNC_FAILURES = 5
_MAX_ERROR_LENGTH = 500


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
            if key is None:
                continue
            account = accounts.get(str(key))
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
    last_conflict: CustomPropertyValueConflict | None = None
    for _ in range(_WRITE_CONFLICT_RETRIES):
        try:
            set_custom_property_value(
                team_id=team_id, account_id=account_id, definition_id=source.definition_id, value=value
            )
            return True
        except CustomPropertyValueConflict as exc:
            last_conflict = exc  # transient active-value race — the retry soft-deletes the winner's row first
            continue
        except InvalidCustomPropertyValue as exc:
            result.source_errors[str(source.id)] = str(exc)
            return False
    # Retries exhausted on a transient conflict — the value re-syncs next run. Deliberately not
    # recorded as a source error (that would auto-disable a healthy source over an environmental
    # race), but captured so the exhausted-retry case stays visible.
    if last_conflict is not None:
        capture_exception(last_conflict)
    return False


def _read_view(team: Team, view_name: str, columns: list[str]) -> list:
    query = ast.SelectQuery(
        select=[ast.Field(chain=[column]) for column in columns],
        select_from=ast.JoinExpr(table=ast.Field(chain=[view_name])),
    )
    with tags_context(product=Product.CUSTOMER_ANALYTICS, feature=Feature.ACCOUNTS, team_id=team.pk):
        return execute_hogql_query(query, team=team).results or []


def record_sync_outcome(
    *,
    team_id: int,
    saved_query_id: str | UUID,
    view_found: bool = True,
    run_failed: bool = False,
    run_error: str | None = None,
    source_errors: dict[str, str] | None = None,
) -> None:
    """Persist a sync run's outcome onto every enabled source for the view.

    Clean success resets the failure streak; a missing view disables immediately; a whole-run
    failure or a per-source column error increments the streak and auto-disables at the cap.
    """
    source_errors = source_errors or {}
    sources = CustomPropertySource.objects.for_team(team_id).filter(saved_query_id=saved_query_id, is_enabled=True)
    now = timezone.now()
    with transaction.atomic():
        for source in sources:
            source.last_synced_at = now
            if not view_found:
                source.last_sync_error = "View not found"
                source.is_enabled = False
                source.consecutive_failures = 0
            elif run_failed or str(source.id) in source_errors:
                error = run_error if run_failed else source_errors[str(source.id)]
                source.last_sync_error = (error or "Sync failed")[:_MAX_ERROR_LENGTH]
                source.consecutive_failures += 1
                if source.consecutive_failures >= MAX_CONSECUTIVE_SYNC_FAILURES:
                    source.is_enabled = False
            else:
                source.last_sync_error = None
                source.consecutive_failures = 0
            source.save()


def run_custom_property_sync(*, team_id: int, saved_query_id: str | UUID) -> SyncResult:
    """Run one sync and persist its outcome. The Celery task's entrypoint.

    On a hard failure the outcome is recorded (so the failure streak/auto-disable still advance)
    and the error is captured, then re-raised so the run shows as failed.
    """
    try:
        result = sync_custom_property_values(team_id=team_id, saved_query_id=saved_query_id)
    except Exception as e:
        record_sync_outcome(team_id=team_id, saved_query_id=saved_query_id, run_failed=True, run_error=str(e))
        capture_exception(e)
        raise

    record_sync_outcome(
        team_id=team_id,
        saved_query_id=saved_query_id,
        view_found=result.view_found,
        source_errors=result.source_errors,
    )
    return result
