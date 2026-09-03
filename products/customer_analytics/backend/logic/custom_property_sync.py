"""Bulk sync of materialized-view columns into account custom property values.

Reads a configured view via HogQL, matches each row to an account by external_id, and writes the
selected column as that account's custom property value. The account create path uses a sync scoped
to one account.
"""

import dataclasses
from typing import Any
from uuid import UUID

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


@dataclasses.dataclass
class SyncResult:
    view_found: bool
    written: int = 0
    unmatched_keys: int = 0
    accounts_total: int = 0
    rows_fetched: int = 0
    source_errors: dict[str, str] = dataclasses.field(default_factory=dict)


def sync_custom_property_values(
    *, team_id: int, saved_query_id: str | UUID, external_id: str | None = None
) -> SyncResult:
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
        source_column = source.source_column
        if source_column is None:
            continue  # only account sources (which always set source_column) reach this saved-query sync
        missing = [column for column in (source.key_column, source_column) if column not in available_columns]
        if missing:
            result.source_errors[str(source.id)] = f"View {saved_query.name} has no column(s): {', '.join(missing)}"
            continue
        usable.append(source)
        selected_columns.update((source.key_column, source_column))
    if not usable:
        return result

    ordered = sorted(selected_columns)
    column_index = {column: position for position, column in enumerate(ordered)}
    account_ids_by_external_id = _get_account_ids_by_external_id(team_id, external_id=external_id)
    external_ids = sorted(account_ids_by_external_id)
    team = Team.objects.get(id=team_id)
    rows_by_key_column = {
        key_column: _read_view(team, saved_query.name, ordered, key_column, external_ids)
        for key_column in sorted({source.key_column for source in usable})
    }
    result.accounts_total = len(account_ids_by_external_id)
    result.rows_fetched = sum(len(rows) for rows in rows_by_key_column.values())

    unmatched: set[Any] = set()
    for source in usable:
        source_column = source.source_column
        if source_column is None:
            continue
        key_index, value_index = column_index[source.key_column], column_index[source_column]
        for row in rows_by_key_column[source.key_column]:
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


def _get_account_ids_by_external_id(team_id: int, external_id: str | None = None) -> dict[str, UUID]:
    accounts = Account.objects.for_team(team_id).exclude(external_id=None).exclude(external_id="")
    if external_id is not None:
        accounts = accounts.filter(external_id=external_id)
    return {
        external_id: account_id for external_id, account_id in accounts.values_list("external_id", "id") if external_id
    }


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


def _read_view(team: Team, view_name: str, columns: list[str], key_column: str, external_ids: list[str]) -> list:
    """Reads only view rows whose key matches a known account external_id, batching the key filter to
    keep each query small. An unfiltered read would be silently capped by the HogQL default limit —
    views are often orders of magnitude larger than the account set they enrich. Filtering on a single
    key column keeps batches disjoint: a row matches at most one batch, so no duplicates accumulate."""
    rows: list = []
    with tags_context(product=Product.CUSTOMER_ANALYTICS, feature=Feature.ACCOUNTS, team_id=team.pk):
        for start in range(0, len(external_ids), _SYNC_KEYS_PER_QUERY):
            batch = external_ids[start : start + _SYNC_KEYS_PER_QUERY]
            query = ast.SelectQuery(
                select=[ast.Field(chain=[column]) for column in columns],
                select_from=ast.JoinExpr(table=ast.Field(chain=[view_name])),
                where=ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Call(name="toString", args=[ast.Field(chain=[key_column])]),
                    right=ast.Array(exprs=[ast.Constant(value=external_id) for external_id in batch]),
                ),
                limit=ast.Constant(value=MAX_SELECT_RETURNED_ROWS),
            )
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


def sync_custom_properties_for_account(*, team_id: int, external_id: str) -> None:
    """Best-effort synchronous population of warehouse-backed custom properties for one account.

    Runs on the external create path so a workflow that creates an account can read the values
    in its next step. Only materialized views are read — an unmaterialized view would run its raw
    query inside the request. No sync outcome is recorded: failure streaks, auto-disable and
    last_synced_at belong to the scheduled full sync.
    """
    # enrichment must never break account creation — the outer try also covers source discovery,
    # which the queryset's laziness would otherwise let escape
    try:
        saved_query_ids = (
            CustomPropertySource.objects.for_team(team_id)
            .filter(is_enabled=True, source_column__isnull=False, saved_query__table__isnull=False)
            .exclude(saved_query__deleted=True)
            .values_list("saved_query_id", flat=True)
            .distinct()
        )
        for saved_query_id in saved_query_ids:
            try:
                sync_custom_property_values(team_id=team_id, saved_query_id=saved_query_id, external_id=external_id)
            except Exception as e:
                capture_exception(e)
    except Exception as e:
        capture_exception(e)
