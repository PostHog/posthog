from posthog.hogql.ast import SelectQuery
from posthog.hogql.context import HogQLContext

from posthog.hogql.database.argmax import argmax_select
from posthog.hogql.database.models import (
    LazyTable,
    IntegerDatabaseField,
    StringDatabaseField,
    DateTimeDatabaseField,
    StringJSONDatabaseField,
    Table,
    FieldOrTable,
    LazyTableToAdd,
    LazyJoinToAdd,
)
from posthog.hogql.errors import ResolutionError

GROUPS_TABLE_FIELDS = {
    "index": IntegerDatabaseField(name="group_type_index"),
    "team_id": IntegerDatabaseField(name="team_id"),
    "key": StringDatabaseField(name="group_key"),
    "created_at": DateTimeDatabaseField(name="created_at"),
    "updated_at": DateTimeDatabaseField(name="_timestamp"),
    "properties": StringJSONDatabaseField(name="group_properties"),
}


def select_from_groups_table(requested_fields: dict[str, list[str | int]]):
    return argmax_select(
        table_name="raw_groups",
        select_fields=requested_fields,
        group_fields=["index", "key"],
        argmax_field="updated_at",
    )


def join_with_group_n_table(group_index: int):
    def join_with_group_table(
        join_to_add: LazyJoinToAdd,
        context: HogQLContext,
        node: SelectQuery,
    ):
        from posthog.hogql import ast

        if not join_to_add.fields_accessed:
            raise ResolutionError("No fields requested from person_distinct_ids")

        select_query = select_from_groups_table(join_to_add.fields_accessed)
        select_query.where = ast.CompareOperation(
            left=ast.Field(chain=["index"]),
            op=ast.CompareOperationOp.Eq,
            right=ast.Constant(value=group_index),
        )

        join_expr = ast.JoinExpr(table=select_query)
        join_expr.join_type = "LEFT JOIN"
        join_expr.alias = join_to_add.to_table
        join_expr.constraint = ast.JoinConstraint(
            expr=ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=[join_to_add.from_table, f"$group_{group_index}"]),
                right=ast.Field(chain=[join_to_add.to_table, "key"]),
            ),
            constraint_type="ON",
        )

        return join_expr

    return join_with_group_table


class RawGroupsTable(Table):
    fields: dict[str, FieldOrTable] = GROUPS_TABLE_FIELDS

    def to_printed_clickhouse(self, context):
        return "groups"

    def to_printed_hogql(self):
        return "raw_groups"


class GroupsTable(LazyTable):
    fields: dict[str, FieldOrTable] = GROUPS_TABLE_FIELDS

    def lazy_select(self, table_to_add: LazyTableToAdd, context, node):
        return select_from_groups_table(table_to_add.fields_accessed)

    def to_printed_clickhouse(self, context):
        return "groups"

    def to_printed_hogql(self):
        return "groups"
