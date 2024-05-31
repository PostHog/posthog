import posthoganalytics

from posthog.hogql.ast import SelectQuery
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.argmax import argmax_select
from posthog.hogql.database.models import (
    IntegerDatabaseField,
    LazyTable,
    FieldOrTable,
    LazyTableToAdd,
    LazyJoinToAdd,
    StringDatabaseField,
)
from posthog.hogql.errors import ResolutionError
from posthog.models.organization import Organization


# :NOTE: We already have person_distinct_ids.py, which most tables link to. This persons_pdi.py is a hack to
# make "select persons.pdi.distinct_id from persons" work while avoiding circular imports. Don't use directly.
def persons_pdi_select(requested_fields: dict[str, list[str | int]]):
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


# :NOTE: We already have person_distinct_ids.py, which most tables link to. This persons_pdi.py is a hack to
# make "select persons.pdi.distinct_id from persons" work while avoiding circular imports. Don't use directly.
def persons_pdi_join(
    join_to_add: LazyJoinToAdd,
    context: HogQLContext,
    node: SelectQuery,
):
    from posthog.hogql import ast

    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from person_distinct_ids")
    join_expr = ast.JoinExpr(table=persons_pdi_select(join_to_add.fields_accessed))
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
    join_expr.alias = join_to_add.to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=[join_to_add.from_table, "id"]),
            right=ast.Field(chain=[join_to_add.to_table, "person_id"]),
        ),
        constraint_type="ON",
    )
    return join_expr


# :NOTE: We already have person_distinct_ids.py, which most tables link to. This persons_pdi.py is a hack to
# make "select persons.pdi.distinct_id from persons" work while avoiding circular imports. Don't use directly.
class PersonsPDITable(LazyTable):
    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "distinct_id": StringDatabaseField(name="distinct_id"),
        "person_id": StringDatabaseField(name="person_id"),
    }

    def lazy_select(self, table_to_add: LazyTableToAdd, context, node):
        return persons_pdi_select(table_to_add.fields_accessed)

    def to_printed_clickhouse(self, context):
        return "person_distinct_id2"

    def to_printed_hogql(self):
        return "person_distinct_ids"
