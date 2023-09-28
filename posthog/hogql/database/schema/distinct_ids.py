from typing import Dict, List

from posthog.hogql.database.argmax import argmax_select
from posthog.hogql.database.models import (
    IntegerDatabaseField,
    StringDatabaseField,
    LazyTable,
    FieldOrTable,
)
from posthog.hogql.errors import HogQLException

# :NOTE: This is a hack to avoid circular imports, and to make "select distinct_ids.distinct_id from persons" work.
# You shouldn't use these functions directly. Use "person_distinct_ids" and PersonDistinctIds instead.
def distinct_ids_select(requested_fields: Dict[str, List[str]]):
    # Always include "person_id", as it's the key we use to make further joins, and it'd be great if it's available
    if "person_id" not in requested_fields:
        requested_fields = {**requested_fields, "person_id": ["person_id"]}
    return argmax_select(
        table_name="raw_person_distinct_ids",
        select_fields=requested_fields,
        group_fields=["distinct_id"],
        argmax_field="version",
        deleted_field="is_deleted",
    )


# :NOTE: This is a hack to avoid circular imports, and to make "select distinct_ids.distinct_id from persons" work.
# You shouldn't use these functions directly. Use "person_distinct_ids" and PersonDistinctIds instead.
def distinct_ids_join(from_table: str, to_table: str, requested_fields: Dict[str, List[str]]):
    from posthog.hogql import ast

    if not requested_fields:
        raise HogQLException("No fields requested from person_distinct_ids")
    join_expr = ast.JoinExpr(table=distinct_ids_select(requested_fields))
    join_expr.join_type = "INNER JOIN"
    join_expr.alias = to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=[from_table, "id"]),
            right=ast.Field(chain=[to_table, "person_id"]),
        )
    )
    return join_expr


# :NOTE: This is a hack to avoid circular imports, and to make "select distinct_ids.distinct_id from persons" work.
# You shouldn't use these functions directly. Use "person_distinct_ids" and PersonDistinctIds instead.
class DistinctIdsTable(LazyTable):
    fields: Dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "distinct_id": StringDatabaseField(name="distinct_id"),
        "person_id": StringDatabaseField(name="person_id"),
    }

    def lazy_select(self, requested_fields: Dict[str, List[str]]):
        return distinct_ids_select(requested_fields)

    def to_printed_clickhouse(self, context):
        return "person_distinct_id2"

    def to_printed_hogql(self):
        return "person_distinct_ids"
