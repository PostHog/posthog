from typing import Any, Callable, Dict, List

from posthog.hogql.database.models import (
    Table,
    IntegerDatabaseField,
    StringDatabaseField,
    BooleanDatabaseField,
    LazyJoin,
    LazyTable,
)
from posthog.hogql.database.schema.persons import PersonsTable, join_with_persons_table
from posthog.hogql.errors import HogQLException


def select_from_person_distinct_ids_table(requested_fields: Dict[str, Any]):
    from posthog.hogql import ast

    if not requested_fields:
        requested_fields = {"person_id": ast.Field(chain=["person_id"])}

    fields_to_select: List[ast.Expr] = []
    argmax_version: Callable[[ast.Expr], ast.Expr] = lambda field: ast.Call(
        name="argMax", args=[field, ast.Field(chain=["version"])]
    )
    for field, expr in requested_fields.items():
        if field != "distinct_id":
            fields_to_select.append(ast.Alias(alias=field, expr=argmax_version(expr)))

    distinct_id = ast.Field(chain=["distinct_id"])

    return ast.SelectQuery(
        select=fields_to_select + [distinct_id],
        select_from=ast.JoinExpr(table=ast.Field(chain=["raw_person_distinct_ids"])),
        group_by=[distinct_id],
        having=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=argmax_version(ast.Field(chain=["is_deleted"])),
            right=ast.Constant(value=0),
        ),
    )


def join_with_person_distinct_ids_table(from_table: str, to_table: str, requested_fields: Dict[str, Any]):
    from posthog.hogql import ast

    if not requested_fields:
        raise HogQLException("No fields requested from person_distinct_ids.")
    join_expr = ast.JoinExpr(table=select_from_person_distinct_ids_table(requested_fields))
    join_expr.join_type = "INNER JOIN"
    join_expr.alias = to_table
    join_expr.constraint = ast.CompareOperation(
        op=ast.CompareOperationOp.Eq,
        left=ast.Field(chain=[from_table, "distinct_id"]),
        right=ast.Field(chain=[to_table, "distinct_id"]),
    )
    return join_expr


class RawPersonDistinctIdTable(Table):
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    distinct_id: StringDatabaseField = StringDatabaseField(name="distinct_id")
    person_id: StringDatabaseField = StringDatabaseField(name="person_id")
    is_deleted: BooleanDatabaseField = BooleanDatabaseField(name="is_deleted")
    version: IntegerDatabaseField = IntegerDatabaseField(name="version")

    def clickhouse_table(self):
        return "person_distinct_id2"

    def hogql_table(self):
        return "raw_person_distinct_ids"


class PersonDistinctIdTable(LazyTable):
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    distinct_id: StringDatabaseField = StringDatabaseField(name="distinct_id")
    person_id: StringDatabaseField = StringDatabaseField(name="person_id")
    person: LazyJoin = LazyJoin(
        from_field="person_id", join_table=PersonsTable(), join_function=join_with_persons_table
    )

    def lazy_select(self, requested_fields: Dict[str, Any]):
        return select_from_person_distinct_ids_table(requested_fields)

    def clickhouse_table(self):
        return "person_distinct_id2"

    def hogql_table(self):
        return "person_distinct_ids"
