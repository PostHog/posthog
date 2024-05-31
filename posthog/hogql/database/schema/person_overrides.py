from posthog.hogql.ast import SelectQuery
from posthog.hogql.context import HogQLContext

from posthog.hogql.database.argmax import argmax_select
from posthog.hogql.database.models import (
    Table,
    StringDatabaseField,
    DateTimeDatabaseField,
    IntegerDatabaseField,
    FieldOrTable,
    LazyTableToAdd,
    LazyJoinToAdd,
)

from posthog.hogql.errors import ResolutionError
from posthog.schema import HogQLQueryModifiers

PERSON_OVERRIDES_FIELDS: dict[str, FieldOrTable] = {
    "team_id": IntegerDatabaseField(name="team_id"),
    "old_person_id": StringDatabaseField(name="old_person_id"),
    "override_person_id": StringDatabaseField(name="override_person_id"),
    "oldest_event": DateTimeDatabaseField(name="oldest_event"),
    "merged_at": DateTimeDatabaseField(name="merged_at"),
    "created_at": DateTimeDatabaseField(name="created_at"),
}


def select_from_person_overrides_table(requested_fields: dict[str, list[str | int]]):
    return argmax_select(
        table_name="raw_person_overrides",
        select_fields=requested_fields,
        group_fields=["old_person_id"],
        argmax_field="version",
    )


def join_with_person_overrides_table(
    join_to_add: LazyJoinToAdd,
    context: HogQLContext,
    node: SelectQuery,
):
    from posthog.hogql import ast

    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from person_distinct_ids")

    join_expr = ast.JoinExpr(table=select_from_person_overrides_table(join_to_add.fields_accessed))
    join_expr.join_type = "LEFT OUTER JOIN"
    join_expr.alias = join_to_add.to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=[join_to_add.from_table, "event_person_id"]),
            right=ast.Field(chain=[join_to_add.to_table, "old_person_id"]),
        ),
        constraint_type="ON",
    )
    return join_expr


class RawPersonOverridesTable(Table):
    fields: dict[str, FieldOrTable] = {
        **PERSON_OVERRIDES_FIELDS,
        "version": IntegerDatabaseField(name="version"),
    }

    def to_printed_clickhouse(self, context):
        return "person_overrides"

    def to_printed_hogql(self):
        return "raw_person_overrides"


class PersonOverridesTable(Table):
    fields: dict[str, FieldOrTable] = PERSON_OVERRIDES_FIELDS

    def lazy_select(self, table_to_add: LazyTableToAdd, modifiers: HogQLQueryModifiers):
        return select_from_person_overrides_table(table_to_add.fields_accessed)

    def to_printed_clickhouse(self, context):
        return "person_overrides"

    def to_printed_hogql(self):
        return "person_overrides"
