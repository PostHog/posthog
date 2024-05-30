from typing import cast

from posthog.hogql.ast import SelectQuery, And

from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.argmax import argmax_select
from posthog.hogql.database.models import (
    Table,
    StringDatabaseField,
    DateTimeDatabaseField,
    IntegerDatabaseField,
    StringJSONDatabaseField,
    BooleanDatabaseField,
    LazyTable,
    LazyJoin,
    FieldOrTable,
    LazyTableToAdd,
    LazyJoinToAdd,
)
from posthog.hogql.database.schema.util.where_clause_extractor import WhereClauseExtractor
from posthog.hogql.errors import ResolutionError
from posthog.hogql.database.schema.persons_pdi import PersonsPDITable, persons_pdi_join
from posthog.schema import PersonsArgMaxVersion, PersonsJoinMode

PERSONS_FIELDS: dict[str, FieldOrTable] = {
    "id": StringDatabaseField(name="id"),
    "created_at": DateTimeDatabaseField(name="created_at"),
    "team_id": IntegerDatabaseField(name="team_id"),
    "properties": StringJSONDatabaseField(name="properties"),
    "is_identified": BooleanDatabaseField(name="is_identified"),
    "pdi": LazyJoin(
        from_field=["id"],
        join_table=PersonsPDITable(),
        join_function=persons_pdi_join,
    ),
}


def select_from_persons_table(join_or_table: LazyJoinToAdd | LazyTableToAdd, context: HogQLContext, node: SelectQuery):
    version = context.modifiers.personsArgMaxVersion
    if version == PersonsArgMaxVersion.auto:
        version = PersonsArgMaxVersion.v1
        # If selecting properties, use the faster v2 query. Otherwise, v1 is faster.
        for field_chain in join_or_table.fields_accessed.values():
            if field_chain[0] == "properties":
                version = PersonsArgMaxVersion.v2
                break

    if version == PersonsArgMaxVersion.v2:
        from posthog.hogql.parser import parse_select
        from posthog.hogql import ast

        select = cast(
            ast.SelectQuery,
            parse_select(
                """
            SELECT id FROM raw_persons WHERE (id, version) IN (
               SELECT id, max(version) as version
               FROM raw_persons
               GROUP BY id
               HAVING equals(argMax(raw_persons.is_deleted, raw_persons.version), 0)
            )
            """
            ),
        )
        select.settings = HogQLQuerySettings(optimize_aggregation_in_order=True)

        for field_name, field_chain in join_or_table.fields_accessed.items():
            # We need to always select the 'id' field for the join constraint. The field name here is likely to
            # be "persons__id" if anything, but just in case, let's avoid duplicates.
            if field_name != "id":
                select.select.append(
                    ast.Alias(
                        alias=field_name,
                        expr=ast.Field(chain=field_chain),
                    )
                )
    else:
        select = argmax_select(
            table_name="raw_persons",
            select_fields=join_or_table.fields_accessed,
            group_fields=["id"],
            argmax_field="version",
            deleted_field="is_deleted",
        )
        select.settings = HogQLQuerySettings(optimize_aggregation_in_order=True)

    if context.modifiers.optimizeJoinedFilters:
        extractor = WhereClauseExtractor(context)
        extractor.add_local_tables(join_or_table)
        where = extractor.get_inner_where(node)
        if where and select.where:
            select.where = And(exprs=[select.where, where])
        elif where:
            select.where = where

    return select


def join_with_persons_table(
    join_to_add: LazyJoinToAdd,
    context: HogQLContext,
    node: SelectQuery,
):
    from posthog.hogql import ast

    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from persons table")
    join_expr = ast.JoinExpr(table=select_from_persons_table(join_to_add, context, node))
    if context.modifiers.personsJoinMode == PersonsJoinMode.left:
        join_expr.join_type = "LEFT JOIN"
    else:
        join_expr.join_type = "INNER JOIN"
    join_expr.alias = join_to_add.to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=[join_to_add.from_table, "person_id"]),
            right=ast.Field(chain=[join_to_add.to_table, "id"]),
        ),
        constraint_type="ON",
    )
    return join_expr


class RawPersonsTable(Table):
    fields: dict[str, FieldOrTable] = {
        **PERSONS_FIELDS,
        "is_deleted": BooleanDatabaseField(name="is_deleted"),
        "version": IntegerDatabaseField(name="version"),
    }

    def to_printed_clickhouse(self, context):
        return "person"

    def to_printed_hogql(self):
        return "raw_persons"


class PersonsTable(LazyTable):
    fields: dict[str, FieldOrTable] = PERSONS_FIELDS

    def lazy_select(self, table_to_add: LazyTableToAdd, context, node):
        return select_from_persons_table(table_to_add, context, node)

    def to_printed_clickhouse(self, context):
        return "person"

    def to_printed_hogql(self):
        return "persons"
