from posthog.hogql.ast import SelectQuery
from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.argmax import argmax_select
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    LazyJoinToAdd,
    LazyTable,
    LazyTableToAdd,
    StringDatabaseField,
    Table,
)
from posthog.hogql.errors import ResolutionError

ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_FIELDS: dict[str, FieldOrTable] = {
    "team_id": IntegerDatabaseField(name="team_id", nullable=False),
    "fingerprint": StringDatabaseField(name="fingerprint", nullable=False),
    "issue_id": StringDatabaseField(name="issue_id", nullable=False),
}


def join_with_error_tracking_issue_fingerprint_overrides_table(
    join_to_add: LazyJoinToAdd,
    context: HogQLContext,
    node: SelectQuery,
):
    from posthog.hogql import ast

    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from error_tracking_issue_fingerprint_overrides")
    join_expr = ast.JoinExpr(
        table=select_from_error_tracking_issue_fingerprint_overrides_table(join_to_add.fields_accessed)
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


def select_from_error_tracking_issue_fingerprint_overrides_table(requested_fields: dict[str, list[str | int]]):
    # Always include "issue_id", as it's the key we use to make further joins, and it'd be great if it's available
    if "issue_id" not in requested_fields:
        requested_fields = {**requested_fields, "issue_id": ["issue_id"]}
    select = argmax_select(
        table_name="raw_error_tracking_issue_fingerprint_overrides",
        select_fields=requested_fields,
        group_fields=["fingerprint"],
        argmax_field="version",
        deleted_field="is_deleted",
    )
    select.settings = HogQLQuerySettings(optimize_aggregation_in_order=True)
    return select


class RawErrorTrackingIssueFingerprintOverridesTable(Table):
    fields: dict[str, FieldOrTable] = {
        **ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_FIELDS,
        "is_deleted": BooleanDatabaseField(name="is_deleted", nullable=False),
        "version": IntegerDatabaseField(name="version", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return "error_tracking_issue_fingerprint_overrides"

    def to_printed_hogql(self):
        return "raw_error_tracking_issue_fingerprint_overrides"


class ErrorTrackingIssueFingerprintOverridesTable(LazyTable):
    fields: dict[str, FieldOrTable] = ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_FIELDS

    def lazy_select(
        self,
        table_to_add: LazyTableToAdd,
        context: HogQLContext,
        node: SelectQuery,
    ):
        return select_from_error_tracking_issue_fingerprint_overrides_table(table_to_add.fields_accessed)

    def to_printed_clickhouse(self, context):
        return "error_tracking_issue_fingerprint_overrides"

    def to_printed_hogql(self):
        return "error_tracking_issue_fingerprint_overrides"
