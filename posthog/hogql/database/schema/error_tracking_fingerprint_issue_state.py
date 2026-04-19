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


def join_with_error_tracking_fingerprint_issue_state_table(
    join_to_add: LazyJoinToAdd,
    context: HogQLContext,
    node: SelectQuery,
):
    from posthog.hogql import ast

    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from error_tracking_fingerprint_issue_state")
    join_expr = ast.JoinExpr(
        table=select_from_error_tracking_fingerprint_issue_state_table(join_to_add.fields_accessed)
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
        return select_from_error_tracking_fingerprint_issue_state_table(table_to_add.fields_accessed)

    def to_printed_clickhouse(self, context):
        return "error_tracking_fingerprint_issue_state"

    def to_printed_hogql(self):
        return "error_tracking_fingerprint_issue_state"
