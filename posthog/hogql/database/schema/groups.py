from typing import Dict, Any, List, Callable

from posthog.hogql.database.models import (
    LazyTable,
    IntegerDatabaseField,
    StringDatabaseField,
    DateTimeDatabaseField,
    StringJSONDatabaseField,
    Table,
)


def select_from_groups_table(requested_fields: Dict[str, Any]):
    from posthog.hogql import ast

    if not requested_fields:
        requested_fields = {}
    if "index" not in requested_fields:
        requested_fields["index"] = ast.Field(chain=["index"])
    if "key" not in requested_fields:
        requested_fields["key"] = ast.Field(chain=["key"])

    fields_to_select: List[ast.Expr] = []
    fields_to_group: List[ast.Expr] = []
    argmax_version: Callable[[ast.Expr], ast.Expr] = lambda field: ast.Call(
        name="argMax", args=[field, ast.Field(chain=["updated_at"])]
    )
    for field, expr in requested_fields.items():
        if field == "index" or field == "key" or field == "updated_at":
            fields_to_select.append(ast.Alias(alias=field, expr=expr))
            fields_to_group.append(expr)
        else:
            fields_to_select.append(ast.Alias(alias=field, expr=argmax_version(expr)))

    return ast.SelectQuery(
        select=fields_to_select,
        select_from=ast.JoinExpr(table=ast.Field(chain=["raw_groups"])),
        group_by=fields_to_group,
    )


class RawGroupsTable(Table):
    index: IntegerDatabaseField = IntegerDatabaseField(name="group_type_index")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")

    key: StringDatabaseField = StringDatabaseField(name="group_key")
    created_at: DateTimeDatabaseField = DateTimeDatabaseField(name="created_at")
    updated_at: DateTimeDatabaseField = DateTimeDatabaseField(name="_timestamp")
    properties: StringJSONDatabaseField = StringJSONDatabaseField(name="group_properties")

    def clickhouse_table(self):
        return "groups"

    def hogql_table(self):
        return "groups"


class GroupsTable(LazyTable):
    index: IntegerDatabaseField = IntegerDatabaseField(name="group_type_index")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")

    key: StringDatabaseField = StringDatabaseField(name="group_key")
    created_at: DateTimeDatabaseField = DateTimeDatabaseField(name="created_at")
    updated_at: DateTimeDatabaseField = DateTimeDatabaseField(name="_timestamp")
    properties: StringJSONDatabaseField = StringJSONDatabaseField(name="group_properties")

    def lazy_select(self, requested_fields: Dict[str, Any]):
        return select_from_groups_table(requested_fields)

    def clickhouse_table(self):
        return "groups"

    def hogql_table(self):
        return "groups"
