from typing import Any, Dict, List
from posthog.hogql.ast import SelectQuery
from posthog.hogql.context import HogQLContext

from posthog.hogql.database.argmax import argmax_select
from posthog.hogql.database.models import (
    Table,
    StringDatabaseField,
    DateTimeDatabaseField,
    IntegerDatabaseField,
    FieldOrTable,
)

from posthog.hogql.errors import HogQLException
from posthog.schema import HogQLQueryModifiers

PERSON_OVERRIDES_FIELDS: Dict[str, FieldOrTable] = {
    "team_id": IntegerDatabaseField(name="team_id"),
    "old_person_id": StringDatabaseField(name="old_person_id"),
    "override_person_id": StringDatabaseField(name="override_person_id"),
    "oldest_event": DateTimeDatabaseField(name="oldest_event"),
    "merged_at": DateTimeDatabaseField(name="merged_at"),
    "created_at": DateTimeDatabaseField(name="created_at"),
}


def select_from_person_overrides_table(requested_fields: Dict[str, List[str]]):
    return argmax_select(
        table_name="raw_person_overrides",
        select_fields=requested_fields,
        group_fields=["old_person_id"],
        argmax_field="version",
    )


def join_with_person_overrides_table(
    from_table: str,
    to_table: str,
    requested_fields: Dict[str, Any],
    context: HogQLContext,
    node: SelectQuery,
):
    from posthog.hogql import ast

    if not requested_fields:
        raise HogQLException("No fields requested from person_distinct_ids")

    join_expr = ast.JoinExpr(table=select_from_person_overrides_table(requested_fields))
    join_expr.join_type = "LEFT OUTER JOIN"
    join_expr.alias = to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=[from_table, "event_person_id"]),
            right=ast.Field(chain=[to_table, "old_person_id"]),
        )
    )
    return join_expr


class RawPersonOverridesTable(Table):
    fields: Dict[str, FieldOrTable] = {
        **PERSON_OVERRIDES_FIELDS,
        "version": IntegerDatabaseField(name="version"),
    }

    def to_printed_clickhouse(self, context):
        return "person_overrides"

    def to_printed_hogql(self):
        return "raw_person_overrides"


class PersonOverridesTable(Table):
    fields: Dict[str, FieldOrTable] = PERSON_OVERRIDES_FIELDS

    def lazy_select(self, requested_fields: Dict[str, Any], modifiers: HogQLQueryModifiers):
        return select_from_person_overrides_table(requested_fields)

    def to_printed_clickhouse(self, context):
        return "person_overrides"

    def to_printed_hogql(self):
        return "person_overrides"
