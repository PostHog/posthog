from typing import Any, Dict, List

from posthog.hogql.database.models import (
    Table,
    StringDatabaseField,
    DateTimeDatabaseField,
    IntegerDatabaseField,
)

from posthog.hogql.errors import HogQLException


class PersonOverridesTable(Table):
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    old_person_id: StringDatabaseField = StringDatabaseField(name="old_person_id")
    override_person_id: StringDatabaseField = StringDatabaseField(name="override_person_id")
    oldest_event: DateTimeDatabaseField = DateTimeDatabaseField(name="oldest_event")
    merged_at: DateTimeDatabaseField = DateTimeDatabaseField(name="merged_at")
    created_at: DateTimeDatabaseField = DateTimeDatabaseField(name="created_at")
    version: IntegerDatabaseField = IntegerDatabaseField(name="version")

    def clickhouse_table(self):
        return "person_overrides"

    def hogql_table(self):
        return "person_overrides"


def select_from_person_overrides_table(requested_fields: Dict[str, Any]):
    from posthog.hogql import ast

    if not requested_fields:
        requested_fields = {
            "override_person_id": ast.Field(chain=["override_person_id"]),
            "old_person_id": ast.Field(chain=["old_person_id"]),
        }

    fields_to_select: List[ast.Expr] = []
    for field, expr in requested_fields.items():
        fields_to_select.append(ast.Alias(alias=field, expr=expr))

    return ast.SelectQuery(
        select=fields_to_select,
        select_from=ast.JoinExpr(table=ast.Field(chain=["person_overrides"])),
    )


def join_with_person_overrides_table(from_table: str, to_table: str, requested_fields: Dict[str, Any]):
    from posthog.hogql import ast

    if not requested_fields:
        raise HogQLException("No fields requested from person_distinct_ids.")

    join_expr = ast.JoinExpr(table=select_from_person_overrides_table(requested_fields))
    join_expr.join_type = "LEFT OUTER JOIN"
    join_expr.alias = "overrides"
    join_expr.constraint = ast.CompareOperation(
        op=ast.CompareOperationOp.Eq,
        left=ast.Field(chain=[from_table, "person_id"]),
        right=ast.Field(chain=[to_table, "old_person_id"]),
    )
    return join_expr
