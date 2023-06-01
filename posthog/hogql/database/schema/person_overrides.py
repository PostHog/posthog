from typing import Any, Dict, List, Callable

from posthog.hogql.database.models import (
    Table,
    StringDatabaseField,
    DateTimeDatabaseField,
    IntegerDatabaseField,
)

from posthog.hogql.errors import HogQLException


def select_from_person_overrides_table(requested_fields: Dict[str, Any]):
    from posthog.hogql import ast

    if not requested_fields:
        requested_fields = {}

    table_name = "raw_person_overrides"
    required_fields = ["old_person_id", "override_person_id"]
    for key in requested_fields:
        if key in required_fields:
            requested_fields[key] = ast.Field(chain=[table_name, key])

    argmax_version: Callable[[ast.Expr], ast.Expr] = lambda field: ast.Call(
        name="argMax", args=[field, ast.Field(chain=[table_name, "version"])]
    )

    fields_to_select: List[ast.Expr] = [
        ast.Alias(alias=field, expr=argmax_version(expr)) for field, expr in requested_fields.items()
    ]

    return ast.SelectQuery(
        select=fields_to_select,
        select_from=ast.JoinExpr(table=ast.Field(chain=[table_name])),
        group_by=[ast.Field(chain=[table_name, "override_person_id"])],
    )


def join_with_person_overrides_table(from_table: str, to_table: str, requested_fields: Dict[str, Any]):
    from posthog.hogql import ast

    if not requested_fields:
        raise HogQLException("No fields requested from person_distinct_ids.")

    join_expr = ast.JoinExpr(table=select_from_person_overrides_table(requested_fields))
    join_expr.join_type = "LEFT OUTER JOIN"
    join_expr.alias = to_table
    join_expr.constraint = ast.CompareOperation(
        op=ast.CompareOperationOp.Eq,
        left=ast.Field(chain=[from_table, "person_id"]),
        right=ast.Field(chain=[to_table, "old_person_id"]),
    )
    return join_expr


class RawPersonOverridesTable(Table):
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


class PersonOverridesTable(Table):
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    old_person_id: StringDatabaseField = StringDatabaseField(name="old_person_id")
    override_person_id: StringDatabaseField = StringDatabaseField(name="override_person_id")
    oldest_event: DateTimeDatabaseField = DateTimeDatabaseField(name="oldest_event")
    merged_at: DateTimeDatabaseField = DateTimeDatabaseField(name="merged_at")
    created_at: DateTimeDatabaseField = DateTimeDatabaseField(name="created_at")

    def lazy_select(self, requested_fields: Dict[str, Any]):
        return select_from_person_overrides_table(requested_fields)

    def clickhouse_table(self):
        return "person_overrides"

    def hogql_table(self):
        return "person_overrides"
