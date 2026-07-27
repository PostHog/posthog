from typing import Any, Optional

from posthog.hogql.ast import SelectQuery
from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    LazyJoinToAdd,
    LazyTable,
    LazyTableToAdd,
    StringDatabaseField,
    Table,
    UUIDDatabaseField,
)
from posthog.hogql.errors import ResolutionError

# Key used to pass pending fingerprint-issue-state updates through HogQLContext.data_to_ingest.
PENDING_UPDATES_HOGQL_CONTEXT_KEY = "error_tracking_fingerprints"

ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_FIELDS: dict[str, FieldOrTable] = {
    "team_id": IntegerDatabaseField(name="team_id", nullable=False),
    "fingerprint": StringDatabaseField(
        name="fingerprint",
        nullable=False,
        description="Exception fingerprint that groups matching errors; matches `events.properties.$exception_fingerprint`.",
    ),
    "issue_id": StringDatabaseField(
        name="issue_id",
        nullable=True,
        description="Identifier of the error tracking issue this fingerprint belongs to.",
    ),
    "issue_name": StringDatabaseField(
        name="issue_name", nullable=True, description="Display name of the issue (latest version)."
    ),
    "issue_description": StringDatabaseField(
        name="issue_description", nullable=True, description="Description of the issue (latest version)."
    ),
    "issue_status": StringDatabaseField(
        name="issue_status", nullable=True, description="Current status of the issue, e.g. 'active', 'resolved'."
    ),
    "assigned_user_id": IntegerDatabaseField(
        name="assigned_user_id", nullable=True, description="User the issue is assigned to, if any."
    ),
    "assigned_role_id": UUIDDatabaseField(
        name="assigned_role_id", nullable=True, description="Role the issue is assigned to, if any."
    ),
    "first_seen": DateTimeDatabaseField(
        name="first_seen", nullable=True, description="When the issue was first observed (in UTC)."
    ),
}

RAW_TABLE_NAME = "raw_error_tracking_fingerprint_issue_state"

_ISSUE_STATE_COLUMNS: list[str] = [
    "fingerprint",
    "issue_id",
    "issue_name",
    "issue_description",
    "issue_status",
    "assigned_user_id",
    "assigned_role_id",
    "first_seen",
    "is_deleted",
    "version",
]


def join_with_error_tracking_fingerprint_issue_state_table(
    join_to_add: LazyJoinToAdd,
    context: HogQLContext,
    node: SelectQuery,
):
    from posthog.hogql import ast

    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from error_tracking_fingerprint_issue_state")
    pending_updates = context.data_to_ingest.get(PENDING_UPDATES_HOGQL_CONTEXT_KEY) or []
    join_expr = ast.JoinExpr(
        table=select_from_error_tracking_fingerprint_issue_state_table(
            join_to_add.fields_accessed, pending_updates=pending_updates
        )
    )
    join_expr.join_type = "LEFT OUTER JOIN"
    join_expr.alias = join_to_add.to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Call(
                name="cityHash64",
                args=[ast.Field(chain=[join_to_add.from_table, "properties", "$exception_fingerprint"])],
            ),
            right=ast.Field(chain=[join_to_add.to_table, "fp_hash"]),
        ),
        constraint_type="ON",
    )
    return join_expr


# Tuple wrap defeats argMax's NULL-skip so unassignments (NULL at latest
# version) don't return stale prior values.
_ARGMAX_FIELDS: tuple[str, ...] = (
    "issue_id",
    "issue_name",
    "issue_description",
    "issue_status",
    "assigned_user_id",
    "assigned_role_id",
    "first_seen",
    "fingerprint",
)


def select_from_error_tracking_fingerprint_issue_state_table(
    requested_fields: dict[str, list[str | int]],
    pending_updates: Optional[list[dict[str, Any]]] = None,
):
    from posthog.hogql import ast

    if "issue_id" not in requested_fields:
        requested_fields = {**requested_fields, "issue_id": ["issue_id"]}

    # GROUP BY the UInt64 hash — smaller hashmap buckets than the raw string.
    # Collision probability ~N^2/2^65 is effectively zero at fingerprint scale.
    fp_hash_alias = ast.Alias(
        alias="fp_hash",
        expr=ast.Call(name="cityHash64", args=[ast.Field(chain=[RAW_TABLE_NAME, "fingerprint"])]),
    )

    # Wrap in `toNullable(...)` so unmatched LEFT OUTER JOIN rows produce real
    # NULLs (CH `join_use_nulls=0` returns type defaults for non-Nullable cols
    # like `issue_id UUID` / `issue_status VARCHAR`, which silently breaks
    # `isNotNull(...)` filters downstream).
    select_exprs: list[ast.Expr] = [fp_hash_alias]
    for field_name in requested_fields:
        if field_name == "fp_hash":
            continue
        if field_name in _ARGMAX_FIELDS:
            select_exprs.append(
                ast.Alias(
                    alias=field_name,
                    expr=ast.Call(
                        name="toNullable",
                        args=[
                            ast.Call(
                                name="tupleElement",
                                args=[
                                    ast.Call(
                                        name="argMax",
                                        args=[
                                            ast.Call(
                                                name="tuple",
                                                args=[ast.Field(chain=[RAW_TABLE_NAME, field_name])],
                                            ),
                                            ast.Field(chain=[RAW_TABLE_NAME, "version"]),
                                        ],
                                    ),
                                    ast.Constant(value=1),
                                ],
                            )
                        ],
                    ),
                )
            )

    select = ast.SelectQuery(
        select=select_exprs,
        select_from=ast.JoinExpr(table=ast.Field(chain=[RAW_TABLE_NAME])),
        group_by=[ast.Field(chain=["fp_hash"])],
        having=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Call(
                name="argMax",
                args=[
                    ast.Field(chain=[RAW_TABLE_NAME, "is_deleted"]),
                    ast.Field(chain=[RAW_TABLE_NAME, "version"]),
                ],
            ),
            right=ast.Constant(value=0),
        ),
    )
    select.settings = HogQLQuerySettings(optimize_aggregation_in_order=True)

    # Historically error tracking used to query 2 datasources and we didn't have that problem described below.
    # Error tracking issue related data lives in Postgres for transactional purposes and in CH for reads when we need to join it with events.
    # It lives in a ReplacingMergeTree table in CH and there is a delay between user mutating an issue and that CH table receiving an update (usually ~5s)
    # This breaks the UX because user often doesn't see his own updates reflected in the refreshed issues list.
    # For that reason whenever user does any mutation to an issue, we construct a row with an updated data on frontend.
    # We then include these rows (called pending updates) when we run a list query and we UNION these rows with the base table.
    # Thanks to that, argMax will pick the latest version of the issue state before that version even reaches CH.
    if pending_updates:
        select.select_from = ast.JoinExpr(
            table=_build_union_with_pending_updates(pending_updates),
            alias=RAW_TABLE_NAME,
        )

    return select


def _build_union_with_pending_updates(pending_updates: list[dict[str, Any]]):  #
    from posthog.hogql import ast

    base = ast.SelectQuery(
        select=[ast.Field(chain=[col]) for col in _ISSUE_STATE_COLUMNS],
        select_from=ast.JoinExpr(table=ast.Field(chain=[RAW_TABLE_NAME])),
    )

    branches: list[ast.SelectQuery | ast.SelectSetQuery] = [base]
    for row in pending_updates:
        branches.append(_pending_update_select(row))

    return ast.SelectSetQuery.create_from_queries(branches, set_operator="UNION ALL")


def _pending_update_select(row: dict[str, Any]):
    from posthog.hogql import ast

    assigned_user_id = row.get("assigned_user_id")
    assigned_role_id = row.get("assigned_role_id")

    column_exprs = {
        "fingerprint": ast.Constant(value=str(row["fingerprint"])),
        "issue_id": ast.Call(name="toUUID", args=[ast.Constant(value=str(row["issue_id"]))]),
        "issue_name": ast.Constant(value=row.get("issue_name")),
        "issue_description": ast.Constant(value=row.get("issue_description")),
        "issue_status": ast.Constant(value=str(row["issue_status"])),
        "assigned_user_id": ast.Call(name="_toInt64", args=[ast.Constant(value=int(assigned_user_id))])
        if assigned_user_id is not None
        else ast.Constant(value=None),
        "assigned_role_id": ast.Call(name="toUUID", args=[ast.Constant(value=str(assigned_role_id))])
        if assigned_role_id is not None
        else ast.Constant(value=None),
        "first_seen": ast.Call(
            name="parseDateTimeBestEffort",
            args=[ast.Constant(value=str(row["first_seen"])), ast.Constant(value="UTC")],
        ),
        "is_deleted": ast.Call(name="_toInt8", args=[ast.Constant(value=int(row.get("is_deleted", 0)))]),
        "version": ast.Call(name="_toInt64", args=[ast.Constant(value=int(row["version"]))]),
    }

    return ast.SelectQuery(
        select=[ast.Alias(alias=col, expr=column_exprs[col]) for col in _ISSUE_STATE_COLUMNS],
    )


class RawErrorTrackingFingerprintIssueStateTable(Table):
    description: str = (
        "Raw ReplacingMergeTree backing the issue state of each exception fingerprint; "
        "rows are versioned, so query the deduplicated `error_tracking_fingerprint_issue_state` table instead."
    )
    fields: dict[str, FieldOrTable] = {
        **ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_FIELDS,
        "is_deleted": BooleanDatabaseField(
            name="is_deleted",
            nullable=False,
            description="Whether this version marks the fingerprint state as deleted.",
        ),
        "version": IntegerDatabaseField(
            name="version",
            nullable=False,
            description="Monotonic version; the latest version wins after deduplication.",
        ),
    }

    def to_printed_clickhouse(self, context):
        return "error_tracking_fingerprint_issue_state"

    def to_printed_hogql(self):
        return "raw_error_tracking_fingerprint_issue_state"


class ErrorTrackingFingerprintIssueStateTable(LazyTable):
    description: str = (
        "Deduplicated latest issue state for each exception fingerprint; "
        "join exception events to their issue via `events.properties.$exception_fingerprint`. One row per fingerprint."
    )
    # `fp_hash` is a computed alias produced by `lazy_select`, not a physical
    # column — so it lives here, not on the raw table.
    fields: dict[str, FieldOrTable] = {
        **ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_FIELDS,
        "fp_hash": IntegerDatabaseField(
            name="fp_hash", nullable=False, description="cityHash64 of the fingerprint, used as the join/group key."
        ),
    }

    def lazy_select(
        self,
        table_to_add: LazyTableToAdd,
        context: HogQLContext,
        node: SelectQuery,
    ):
        pending_updates = context.data_to_ingest.get(PENDING_UPDATES_HOGQL_CONTEXT_KEY) or []
        return select_from_error_tracking_fingerprint_issue_state_table(
            table_to_add.fields_accessed, pending_updates=pending_updates
        )

    def to_printed_clickhouse(self, context):
        return "error_tracking_fingerprint_issue_state"

    def to_printed_hogql(self):
        return "error_tracking_fingerprint_issue_state"
