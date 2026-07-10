from posthog.hogql.ast import SelectQuery
from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.argmax import argmax_select
from posthog.hogql.database.lazy_join_tags import PERSONS
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    LazyJoin,
    LazyJoinToAdd,
    LazyTable,
    LazyTableToAdd,
    StringDatabaseField,
    Table,
)
from posthog.hogql.errors import ResolutionError

PERSON_DISTINCT_IDS_FIELDS: dict[str, FieldOrTable] = {
    "team_id": IntegerDatabaseField(name="team_id", nullable=False),
    "distinct_id": StringDatabaseField(
        name="distinct_id",
        nullable=False,
        description="Client-side distinct_id sent with events; multiple distinct_ids can map to one person.",
    ),
    "person_id": StringDatabaseField(
        name="person_id",
        nullable=False,
        description="Resolved person this distinct_id belongs to; matches `persons.id`.",
    ),
    "person": LazyJoin(
        from_field=["person_id"],
        join_table="persons",
        resolver=PERSONS,
    ),
}


def select_from_person_distinct_ids_table(requested_fields: dict[str, list[str | int]]):
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
    select.settings = HogQLQuerySettings(optimize_aggregation_in_order=True)
    return select


def join_with_person_distinct_ids_table(
    join_to_add: LazyJoinToAdd,
    context: HogQLContext,
    node: SelectQuery,
):
    from posthog.hogql import ast

    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from person_distinct_ids")
    join_expr = ast.JoinExpr(table=select_from_person_distinct_ids_table(join_to_add.fields_accessed))
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
    description: str = (
        "Raw, un-deduplicated distinct_id-to-person mappings (one per version). Query `person_distinct_ids` "
        "instead unless you need to resolve the latest version yourself via `is_deleted`/`version`."
    )
    fields: dict[str, FieldOrTable] = {
        **PERSON_DISTINCT_IDS_FIELDS,
        "is_deleted": BooleanDatabaseField(name="is_deleted", nullable=False),
        "version": IntegerDatabaseField(name="version", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return "person_distinct_id2"

    def to_printed_hogql(self):
        return "raw_person_distinct_ids"


class PersonDistinctIdsTable(LazyTable):
    description: str = (
        "Maps client-side distinct IDs to resolved person IDs. One row per distinct_id; "
        "join to `persons` via the `person` field or `person_id`."
    )
    fields: dict[str, FieldOrTable] = PERSON_DISTINCT_IDS_FIELDS

    def lazy_select(self, table_to_add: LazyTableToAdd, context, node):
        return select_from_person_distinct_ids_table(table_to_add.fields_accessed)

    def to_printed_clickhouse(self, context):
        return "person_distinct_id2"

    def to_printed_hogql(self):
        return "person_distinct_ids"
