from posthog.schema import ErrorTrackingFingerprintIssueStatePhantomRow

from posthog.hogql.ast import SelectQuery
from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.argmax import argmax_select
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

ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_FIELDS: dict[str, FieldOrTable] = {
    "team_id": IntegerDatabaseField(name="team_id", nullable=False),
    "fingerprint": StringDatabaseField(name="fingerprint", nullable=False),
    "issue_id": StringDatabaseField(name="issue_id", nullable=True),
    "issue_name": StringDatabaseField(name="issue_name", nullable=True),
    "issue_description": StringDatabaseField(name="issue_description", nullable=True),
    "issue_status": StringDatabaseField(name="issue_status", nullable=True),
    "assigned_user_id": IntegerDatabaseField(name="assigned_user_id", nullable=True),
    "assigned_role_id": UUIDDatabaseField(name="assigned_role_id", nullable=True),
    "first_seen": DateTimeDatabaseField(name="first_seen", nullable=True),
}


# Columns the argmax subquery references. Must match between the real branch and every phantom branch
# so the UNION ALL typechecks in ClickHouse. Order matters for positional UNION matching.
_UNION_COLUMNS = [
    "team_id",
    "fingerprint",
    "version",
    "is_deleted",
    "issue_id",
    "issue_name",
    "issue_description",
    "issue_status",
    "assigned_user_id",
    "assigned_role_id",
    "first_seen",
]


def join_with_error_tracking_fingerprint_issue_state_table(
    join_to_add: LazyJoinToAdd,
    context: HogQLContext,
    node: SelectQuery,
):
    from posthog.hogql import ast

    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from error_tracking_fingerprint_issue_state")
    join_expr = ast.JoinExpr(
        table=select_from_error_tracking_fingerprint_issue_state_table(
            join_to_add.fields_accessed,
            phantom_rows=context.error_tracking_phantom_fingerprint_states,
            team_id=context.team_id,
        )
    )
    join_expr.join_type = "LEFT OUTER JOIN"
    join_expr.alias = join_to_add.to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=[join_to_add.from_table, "properties", "$exception_fingerprint"]),
            right=ast.Field(chain=[join_to_add.to_table, "fingerprint"]),
        ),
        constraint_type="ON",
    )
    return join_expr


def select_from_error_tracking_fingerprint_issue_state_table(
    requested_fields: dict[str, list[str | int]],
    phantom_rows: list[ErrorTrackingFingerprintIssueStatePhantomRow] | None = None,
    team_id: int | None = None,
):
    from posthog.hogql import ast

    # Always include issue_id as it's the key used for further joins
    if "issue_id" not in requested_fields:
        requested_fields = {**requested_fields, "issue_id": ["issue_id"]}
    select = argmax_select(
        table_name="raw_error_tracking_fingerprint_issue_state",
        select_fields=requested_fields,
        group_fields=["fingerprint"],
        argmax_field="version",
        deleted_field="is_deleted",
    )

    if phantom_rows:
        if team_id is None:
            raise ResolutionError(
                "team_id is required to build phantom fingerprint_issue_state rows; refusing to leak across teams"
            )
        # Replace the direct table reference with a subquery that UNIONs the real table with
        # phantom rows. Phantoms are in-memory overrides supplied by the error tracking query runner
        # so recent UI mutations win argmax(version) while Kafka is catching up. The real branch
        # still references the raw table as a TableType, so HogQL auto-adds the team_id WHERE.
        # Phantom branches explicitly set team_id (server-validated) to be filtered equivalently.
        real_branch = ast.SelectQuery(
            select=[ast.Field(chain=[col]) for col in _UNION_COLUMNS],
            select_from=ast.JoinExpr(table=ast.Field(chain=["raw_error_tracking_fingerprint_issue_state"])),
        )
        phantom_branches: list[ast.SelectQuery | ast.SelectSetQuery] = [
            _build_phantom_select(row, team_id) for row in phantom_rows
        ]
        union = ast.SelectSetQuery.create_from_queries(
            [real_branch, *phantom_branches],
            set_operator="UNION ALL",
        )
        select.select_from = ast.JoinExpr(
            table=union,
            alias="raw_error_tracking_fingerprint_issue_state",
        )

    # Wrap non-group-by fields in toNullable() so that unmatched LEFT JOIN rows
    # produce actual NULLs instead of type defaults (e.g. 00000000-... for UUID).
    # ClickHouse's join_use_nulls=0 (default) only returns NULL for Nullable columns.
    group_fields = {"fingerprint"}
    for i, expr in enumerate(select.select):
        if isinstance(expr, ast.Alias) and expr.alias not in group_fields:
            select.select[i] = ast.Alias(
                alias=expr.alias,
                expr=ast.Call(name="toNullable", args=[expr.expr]),
            )
    select.settings = HogQLQuerySettings(optimize_aggregation_in_order=True)
    return select


def _build_phantom_select(row: ErrorTrackingFingerprintIssueStatePhantomRow, team_id: int) -> "SelectQuery":
    """Build a single-row SELECT of constants mirroring _UNION_COLUMNS in the same order.

    `team_id` is taken from the authenticated context, never from the client payload.
    """
    from posthog.hogql import ast

    def const(value) -> ast.Expr:
        return ast.Constant(value=value)

    def uuid_const(value: str | None) -> ast.Expr:
        if value is None:
            return ast.Constant(value=None)
        # toUUID coerces the string into ClickHouse UUID so the UNION typechecks against the
        # raw table's UUID columns (issue_id, assigned_role_id).
        return ast.Call(name="toUUID", args=[ast.Constant(value=value)])

    issue_status_value = row.issue_status.value if row.issue_status is not None else None

    column_exprs: dict[str, ast.Expr] = {
        "team_id": const(team_id),
        "fingerprint": const(row.fingerprint),
        "version": const(row.version),
        "is_deleted": const(row.is_deleted if row.is_deleted is not None else 0),
        "issue_id": uuid_const(row.issue_id),
        "issue_name": const(row.issue_name),
        "issue_description": const(row.issue_description),
        "issue_status": const(issue_status_value),
        "assigned_user_id": const(row.assigned_user_id),
        "assigned_role_id": uuid_const(row.assigned_role_id),
        # first_seen is never mutated from the UI; phantom leaves it unset so real data wins when
        # downstream queries need it. NULL promotes the UNION type to Nullable(DateTime64).
        "first_seen": const(None),
    }
    return ast.SelectQuery(
        select=[ast.Alias(alias=col, expr=column_exprs[col]) for col in _UNION_COLUMNS],
    )


class RawErrorTrackingFingerprintIssueStateTable(Table):
    fields: dict[str, FieldOrTable] = {
        **ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_FIELDS,
        "is_deleted": BooleanDatabaseField(name="is_deleted", nullable=False),
        "version": IntegerDatabaseField(name="version", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return "error_tracking_fingerprint_issue_state"

    def to_printed_hogql(self):
        return "raw_error_tracking_fingerprint_issue_state"


class ErrorTrackingFingerprintIssueStateTable(LazyTable):
    fields: dict[str, FieldOrTable] = ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_FIELDS

    def lazy_select(
        self,
        table_to_add: LazyTableToAdd,
        context: HogQLContext,
        node: SelectQuery,
    ):
        return select_from_error_tracking_fingerprint_issue_state_table(
            table_to_add.fields_accessed,
            phantom_rows=context.error_tracking_phantom_fingerprint_states,
            team_id=context.team_id,
        )

    def to_printed_clickhouse(self, context):
        return "error_tracking_fingerprint_issue_state"

    def to_printed_hogql(self):
        return "error_tracking_fingerprint_issue_state"
