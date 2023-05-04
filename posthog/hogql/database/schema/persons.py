from typing import Any, Callable, Dict, List

from posthog.hogql.database.models import (
    Table,
    StringDatabaseField,
    DateTimeDatabaseField,
    IntegerDatabaseField,
    StringJSONDatabaseField,
    BooleanDatabaseField,
    LazyTable,
)
from posthog.hogql.errors import HogQLException


def select_from_persons_table(requested_fields: Dict[str, Any]):
    from posthog.hogql import ast

    if not requested_fields:
        raise HogQLException("No fields requested from persons table.")

    fields_to_select: List[ast.Expr] = []
    argmax_version: Callable[[ast.Expr], ast.Expr] = lambda field: ast.Call(
        name="argMax", args=[field, ast.Field(chain=["version"])]
    )
    for field, expr in requested_fields.items():
        if field != "id":
            fields_to_select.append(ast.Alias(alias=field, expr=argmax_version(expr)))

    id = ast.Field(chain=["id"])

    return ast.SelectQuery(
        select=fields_to_select + [id],
        select_from=ast.JoinExpr(table=ast.Field(chain=["raw_persons"])),
        group_by=[id],
        having=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=argmax_version(ast.Field(chain=["is_deleted"])),
            right=ast.Constant(value=0),
        ),
    )


def join_with_persons_table(from_table: str, to_table: str, requested_fields: Dict[str, Any]):
    from posthog.hogql import ast

    if not requested_fields:
        raise HogQLException("No fields requested from persons table.")
    join_expr = ast.JoinExpr(table=select_from_persons_table(requested_fields))
    join_expr.join_type = "INNER JOIN"
    join_expr.alias = to_table
    join_expr.constraint = ast.CompareOperation(
        op=ast.CompareOperationOp.Eq,
        left=ast.Field(chain=[from_table, "person_id"]),
        right=ast.Field(chain=[to_table, "id"]),
    )
    return join_expr


class RawPersonsTable(Table):
    id: StringDatabaseField = StringDatabaseField(name="id")
    created_at: DateTimeDatabaseField = DateTimeDatabaseField(name="created_at")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    properties: StringJSONDatabaseField = StringJSONDatabaseField(name="properties")
    is_identified: BooleanDatabaseField = BooleanDatabaseField(name="is_identified")
    is_deleted: BooleanDatabaseField = BooleanDatabaseField(name="is_deleted")
    version: IntegerDatabaseField = IntegerDatabaseField(name="version")

    def clickhouse_table(self):
        return "person"

    def hogql_table(self):
        return "raw_persons"


class PersonsTable(LazyTable):
    id: StringDatabaseField = StringDatabaseField(name="id")
    created_at: DateTimeDatabaseField = DateTimeDatabaseField(name="created_at")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    properties: StringJSONDatabaseField = StringJSONDatabaseField(name="properties")
    is_identified: BooleanDatabaseField = BooleanDatabaseField(name="is_identified")

    def lazy_select(self, requested_fields: Dict[str, Any]):
        return select_from_persons_table(requested_fields)

    def clickhouse_table(self):
        return "person"

    def hogql_table(self):
        return "persons"
