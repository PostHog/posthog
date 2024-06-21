from posthog.hogql import ast
from posthog.hogql.ast import SelectQuery, And
from posthog.hogql.context import HogQLContext

from posthog.hogql.database.argmax import argmax_select
from posthog.hogql.database.models import (
    Table,
    IntegerDatabaseField,
    StringDatabaseField,
    BooleanDatabaseField,
    LazyJoin,
    LazyTable,
    FieldOrTable,
    LazyTableToAdd,
    LazyJoinToAdd,
)
from posthog.hogql.database.schema.persons import join_with_persons_table
from posthog.hogql.errors import ResolutionError
from posthog.hogql.visitor import clone_expr

PERSON_DISTINCT_IDS_FIELDS = {
    "team_id": IntegerDatabaseField(name="team_id"),
    "distinct_id": StringDatabaseField(name="distinct_id"),
    "person_id": StringDatabaseField(name="person_id"),
    "person": LazyJoin(
        from_field=["person_id"],
        join_table="persons",
        join_function=join_with_persons_table,
    ),
}


def select_from_person_distinct_ids_table(
    requested_fields: dict[str, list[str | int]], context: HogQLContext, node: SelectQuery
):
    # Always include "person_id", as it's the key we use to make further joins, and it'd be great if it's available
    if "person_id" not in requested_fields:
        requested_fields = {**requested_fields, "person_id": ["person_id"]}
    select = argmax_select(
        table_name="raw_person_distinct_ids",
        select_fields=requested_fields,
        group_fields=["distinct_id"],
        argmax_field="version",
        deleted_field="is_deleted",
    )

    if "distinct_ids" in node.type.ctes:
        comparison = clone_expr(
            ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Field(
                    chain=["distinct_id"], type=ast.FieldType(name="distinct_id", table_type=PersonDistinctIdsTable)
                ),
                right=ast.SelectQuery(
                    select=[ast.Field(chain=["distinct_id"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["distinct_ids"])),
                ),
            ),
            clear_types=True,
            clear_locations=True,
        )
        if select.where:
            select.where = And(exprs=[comparison, select.where])
        else:
            select.where = comparison

    return select


def join_with_person_distinct_ids_table(
    join_to_add: LazyJoinToAdd,
    context: HogQLContext,
    node: SelectQuery,
):
    from posthog.hogql import ast

    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from person_distinct_ids")
    join_expr = ast.JoinExpr(table=select_from_person_distinct_ids_table(join_to_add.fields_accessed, context, node))
    join_expr.join_type = "INNER JOIN"
    join_expr.alias = join_to_add.to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=[join_to_add.from_table, "distinct_id"]),
            right=ast.Field(chain=[join_to_add.to_table, "distinct_id"]),
        ),
        constraint_type="ON",
    )
    return join_expr


class RawPersonDistinctIdsTable(Table):
    fields: dict[str, FieldOrTable] = {
        **PERSON_DISTINCT_IDS_FIELDS,
        "is_deleted": BooleanDatabaseField(name="is_deleted"),
        "version": IntegerDatabaseField(name="version"),
    }

    def to_printed_clickhouse(self, context):
        return "person_distinct_id2"

    def to_printed_hogql(self):
        return "raw_person_distinct_ids"


class PersonDistinctIdsTable(LazyTable):
    fields: dict[str, FieldOrTable] = PERSON_DISTINCT_IDS_FIELDS

    def lazy_select(self, table_to_add: LazyTableToAdd, context, node):
        return select_from_person_distinct_ids_table(table_to_add.fields_accessed, context, node)

    def to_printed_clickhouse(self, context):
        return "person_distinct_id2"

    def to_printed_hogql(self):
        return "person_distinct_ids"
