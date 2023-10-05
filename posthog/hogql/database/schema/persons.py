from typing import Dict, List

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
)
from posthog.hogql.errors import HogQLException
from posthog.hogql.database.schema.persons_pdi import PersonsPDITable, persons_pdi_join

PERSONS_FIELDS: Dict[str, FieldOrTable] = {
    "id": StringDatabaseField(name="id"),
    "created_at": DateTimeDatabaseField(name="created_at"),
    "team_id": IntegerDatabaseField(name="team_id"),
    "properties": StringJSONDatabaseField(name="properties"),
    "is_identified": BooleanDatabaseField(name="is_identified"),
    "pdi": LazyJoin(
        from_field="id",
        join_table=PersonsPDITable(),
        join_function=persons_pdi_join,
    ),
}


def select_from_persons_table(requested_fields: Dict[str, List[str]]):
    from posthog.hogql.parser import parse_select
    from posthog.hogql import ast

    query = parse_select(
        """
        SELECT id FROM raw_persons WHERE (id, version) IN (
           SELECT id, max(version) as version
           FROM raw_persons
           GROUP BY id
           HAVING ifNull(equals(argMax(raw_persons.is_deleted, raw_persons.version), 0), 0)
           limit 10
        )
    """
    )

    query.select = []
    for field_name, field_chain in requested_fields.items():
        query.select.append(
            ast.Alias(
                alias=field_name,
                expr=ast.Field(chain=["raw_persons"] + field_chain),
            )
        )
    return query


def join_with_persons_table(from_table: str, to_table: str, requested_fields: Dict[str, List[str]]):
    from posthog.hogql import ast

    if not requested_fields:
        raise HogQLException("No fields requested from persons table")
    join_expr = ast.JoinExpr(table=select_from_persons_table(requested_fields))
    join_expr.join_type = "INNER JOIN"
    join_expr.alias = to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=[from_table, "person_id"]),
            right=ast.Field(chain=[to_table, "id"]),
        )
    )
    return join_expr


class RawPersonsTable(Table):
    fields: Dict[str, FieldOrTable] = {
        **PERSONS_FIELDS,
        "is_deleted": BooleanDatabaseField(name="is_deleted"),
        "version": IntegerDatabaseField(name="version"),
    }

    def to_printed_clickhouse(self, context):
        return "person"

    def to_printed_hogql(self):
        return "raw_persons"


class PersonsTable(LazyTable):
    fields: Dict[str, FieldOrTable] = PERSONS_FIELDS

    def lazy_select(self, requested_fields: Dict[str, List[str]]):
        return select_from_persons_table(requested_fields)

    def to_printed_clickhouse(self, context):
        return "person"

    def to_printed_hogql(self):
        return "persons"
