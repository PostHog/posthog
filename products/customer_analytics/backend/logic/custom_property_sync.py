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

import structlog

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS
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

logger = structlog.get_logger(__name__)

_WRITE_CONFLICT_RETRIES = 3
_SYNC_KEYS_PER_QUERY = 1000

# Mirrors data_modeling's CONSECUTIVE_TIMEOUTS_TO_PAUSE: auto-disable a source that keeps failing.
MAX_CONSECUTIVE_SYNC_FAILURES = 5
_MAX_ERROR_LENGTH = 500


@dataclasses.dataclass
class SyncResult:
    view_found: bool
    written: int = 0
    unmatched_keys: int = 0
    accounts_total: int = 0
    rows_fetched: int = 0
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
    account_ids_by_external_id = _get_account_ids_by_external_id(team_id)
    key_columns = sorted({source.key_column for source in usable})
    external_ids = sorted(account_ids_by_external_id)
    rows = _read_view(Team.objects.get(id=team_id), saved_query.name, ordered, key_columns, external_ids)
    result.accounts_total = len(account_ids_by_external_id)
    result.rows_fetched = len(rows)

    unmatched: set[Any] = set()
    for source in usable:
        key_index, value_index = column_index[source.key_column], column_index[source.source_column]
        for row in rows:
            key = row[key_index]
            if key is None:
                continue
            account_id = account_ids_by_external_id.get(str(key))
            if account_id is None:
                unmatched.add(key)
                continue
            if row[value_index] is None:
                continue
            if _write(team_id=team_id, account_id=account_id, source=source, value=row[value_index], result=result):
                result.written += 1
    result.unmatched_keys = len(unmatched)
    return result


def _get_account_ids_by_external_id(team_id: int) -> dict[str, UUID]:
    accounts = Account.objects.for_team(team_id).exclude(external_id=None).exclude(external_id="")
    return dict(accounts.values_list("external_id", "id"))


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


def _read_view(team: Team, view_name: str, columns: list[str], key_columns: list[str], external_ids: list[str]) -> list:
    """Reads only view rows whose key matches a known account external_id, batching the key filter to
    keep each query small. An unfiltered read would be silently capped by the HogQL default limit —
    views are often orders of magnitude larger than the account set they enrich."""
    rows: list = []
    for start in range(0, len(external_ids), _SYNC_KEYS_PER_QUERY):
        batch = external_ids[start : start + _SYNC_KEYS_PER_QUERY]
        key_matches = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Call(name="toString", args=[ast.Field(chain=[key_column])]),
                right=ast.Array(exprs=[ast.Constant(value=external_id) for external_id in batch]),
            )
            for key_column in key_columns
        ]
        query = ast.SelectQuery(
            select=[ast.Field(chain=[column]) for column in columns],
            select_from=ast.JoinExpr(table=ast.Field(chain=[view_name])),
            where=ast.Or(exprs=key_matches) if len(key_matches) > 1 else key_matches[0],
            limit=ast.Constant(value=MAX_SELECT_RETURNED_ROWS),
        )
        with tags_context(product=Product.CUSTOMER_ANALYTICS, feature=Feature.ACCOUNTS, team_id=team.pk):
            # Runs as a userless system sync, so bypass user-scoped warehouse-view access control
            # (it fails closed without a user); tenant isolation still holds via team.
            batch_rows = execute_hogql_query(query, team=team, bypass_warehouse_access_control=True).results or []
        if len(batch_rows) >= MAX_SELECT_RETURNED_ROWS:
            logger.warning(
                "custom_property_sync.view_read_truncated",
                team_id=team.pk,
                view_name=view_name,
                batch_keys=len(batch),
            )
        rows.extend(batch_rows)
    return rows


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
    logger.info(
        "custom_property_sync.completed",
        team_id=team_id,
        saved_query_id=str(saved_query_id),
        view_found=result.view_found,
        written=result.written,
        unmatched_keys=result.unmatched_keys,
        accounts_total=result.accounts_total,
        rows_fetched=result.rows_fetched,
        source_errors=len(result.source_errors),
    )
    return result
