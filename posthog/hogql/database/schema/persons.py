import posthoganalytics

from posthog.hogql.ast import SelectQuery
from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.argmax import argmax_select
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    LazyJoin,
    LazyTable,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
)
from posthog.hogql.database.schema.persons_pdi import PersonsPDITable, persons_pdi_join
from posthog.hogql.errors import ResolutionError
from posthog.models.organization import Organization
from posthog.schema import HogQLQueryModifiers, PersonsArgMaxVersion

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


def select_from_persons_table(requested_fields: dict[str, list[str | int]], modifiers: HogQLQueryModifiers):
    version = modifiers.personsArgMaxVersion
    if version == PersonsArgMaxVersion.auto:
        version = PersonsArgMaxVersion.v1
        # If selecting properties, use the faster v2 query. Otherwise v1 is faster.
        for field_chain in requested_fields.values():
            if field_chain[0] == "properties":
                version = PersonsArgMaxVersion.v2
                break

    if version == PersonsArgMaxVersion.v2:
        from posthog.hogql import ast
        from posthog.hogql.parser import parse_select

        query = parse_select(
            """
            SELECT id FROM raw_persons WHERE (id, version) IN (
               SELECT id, max(version) as version
               FROM raw_persons
               GROUP BY id
               HAVING equals(argMax(raw_persons.is_deleted, raw_persons.version), 0)
               AND argMax(raw_persons.created_at, raw_persons.version) < now() + interval 1 day
            )
            """
        )
        query.settings = HogQLQuerySettings(optimize_aggregation_in_order=True)

        for field_name, field_chain in requested_fields.items():
            # We need to always select the 'id' field for the join constraint. The field name here is likely to
            # be "persons__id" if anything, but just in case, let's avoid duplicates.
            if field_name != "id":
                query.select.append(
                    ast.Alias(
                        alias=field_name,
                        expr=ast.Field(chain=field_chain),
                    )
                )
        return query
    else:
        select = argmax_select(
            table_name="raw_persons",
            select_fields=requested_fields,
            group_fields=["id"],
            argmax_field="version",
            deleted_field="is_deleted",
            no_future_field="created_at",
        )
        select.settings = HogQLQuerySettings(optimize_aggregation_in_order=True)
        return select


def join_with_persons_table(
    from_table: str,
    to_table: str,
    requested_fields: dict[str, list[str | int]],
    context: HogQLContext,
    node: SelectQuery,
):
    from posthog.hogql import ast

    if not requested_fields:
        raise ResolutionError("No fields requested from persons table")
    join_expr = ast.JoinExpr(table=select_from_persons_table(requested_fields, context.modifiers))

    organization: Organization = context.team.organization if context.team else None
    # TODO: @raquelmsmith: Remove flag check and use left join for all once deletes are caught up
    use_inner_join = (
        posthoganalytics.feature_enabled(
            "personless-events-not-supported",
            str(context.team.uuid),
            groups={"organization": str(organization.id)},
            group_properties={
                "organization": {
                    "id": str(organization.id),
                    "created_at": organization.created_at,
                }
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
        if organization and context.team
        else False
    )
    if use_inner_join:
        join_expr.join_type = "INNER JOIN"
    else:
        join_expr.join_type = "LEFT JOIN"

    join_expr.alias = to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=[from_table, "person_id"]),
            right=ast.Field(chain=[to_table, "id"]),
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

    def lazy_select(self, requested_fields: dict[str, list[str | int]], context, node):
        return select_from_persons_table(requested_fields, context.modifiers)

    def to_printed_clickhouse(self, context):
        return "person"

    def to_printed_hogql(self):
        return "persons"
