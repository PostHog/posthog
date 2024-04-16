from typing import Dict, List

from posthog.hogql.database.models import (
    StringDatabaseField,
    IntegerDatabaseField,
    Table,
    LazyJoin,
    LazyTable,
    FieldOrTable,
)
from posthog.hogql.database.schema.persons import join_with_persons_table

COHORT_PEOPLE_FIELDS = {
    "person_id": StringDatabaseField(name="person_id"),
    "cohort_id": IntegerDatabaseField(name="cohort_id"),
    "team_id": IntegerDatabaseField(name="team_id"),
    "person": LazyJoin(
        from_field=["person_id"],
        join_table="persons",
        join_function=join_with_persons_table,
    ),
}


def select_from_cohort_people_table(requested_fields: Dict[str, List[str | int]], team_id: int):
    from posthog.hogql import ast
    from posthog.models import Cohort

    cohort_tuples = list(Cohort.objects.filter(is_static=False, team_id=team_id).values_list("id", "version"))

    table_name = "raw_cohort_people"

    if "person_id" not in requested_fields:
        requested_fields = {**requested_fields, "person_id": ["person_id"]}
    if "cohort_id" not in requested_fields:
        requested_fields = {**requested_fields, "cohort_id": ["cohort_id"]}

    fields: List[ast.Expr] = [
        ast.Alias(alias=name, expr=ast.Field(chain=[table_name] + chain)) for name, chain in requested_fields.items()
    ]

    return ast.SelectQuery(
        select=fields,
        select_from=ast.JoinExpr(table=ast.Field(chain=[table_name])),
        where=ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Tuple(
                        exprs=[ast.Field(chain=[table_name, "cohort_id"]), ast.Field(chain=[table_name, "version"])]
                    ),
                    right=ast.Constant(value=cohort_tuples),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Gt,
                    left=ast.Field(chain=[table_name, "sign"]),
                    right=ast.Constant(value=0),
                ),
            ]
        ),
    )


class RawCohortPeople(Table):
    fields: Dict[str, FieldOrTable] = {
        **COHORT_PEOPLE_FIELDS,
        "sign": IntegerDatabaseField(name="sign"),
        "version": IntegerDatabaseField(name="version"),
    }

    def to_printed_clickhouse(self, context):
        return "cohortpeople"

    def to_printed_hogql(self):
        return "raw_cohort_people"


class CohortPeople(LazyTable):
    fields: Dict[str, FieldOrTable] = COHORT_PEOPLE_FIELDS

    def lazy_select(self, requested_fields: Dict[str, List[str | int]], context, node):
        return select_from_cohort_people_table(requested_fields, context.team_id)

    def to_printed_clickhouse(self, context):
        return "cohortpeople"

    def to_printed_hogql(self):
        return "cohort_people"
