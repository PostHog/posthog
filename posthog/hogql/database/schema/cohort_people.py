from posthog.hogql.database.models import (
    FieldOrTable,
    IntegerDatabaseField,
    LazyJoin,
    LazyTable,
    LazyTableToAdd,
    StringDatabaseField,
    Table,
)
from posthog.hogql.database.schema.persons import join_with_persons_table

COHORT_PEOPLE_FIELDS = {
    "person_id": StringDatabaseField(name="person_id", nullable=False),
    "cohort_id": IntegerDatabaseField(name="cohort_id", nullable=False),
    "team_id": IntegerDatabaseField(name="team_id", nullable=False),
    "person": LazyJoin(
        from_field=["person_id"],
        join_table="persons",
        join_function=join_with_persons_table,
    ),
}


def select_from_cohort_people_table(requested_fields: dict[str, list[str | int]], project_id: int):
    from posthog.hogql import ast

    from posthog.models import Cohort

    cohort_tuples = list(
        Cohort.objects.filter(is_static=False, team__project_id=project_id, deleted=False)
        .exclude(version__isnull=True)
        .values_list("id", "version")
    )

    table_name = "raw_cohort_people"

    if "person_id" not in requested_fields:
        requested_fields = {**requested_fields, "person_id": ["person_id"]}
    if "cohort_id" not in requested_fields:
        requested_fields = {**requested_fields, "cohort_id": ["cohort_id"]}

    fields: list[ast.Expr] = [
        ast.Alias(alias=name, expr=ast.Field(chain=[table_name, *chain])) for name, chain in requested_fields.items()
    ]

    return ast.SelectQuery(
        select=fields,
        distinct=True,
        select_from=ast.JoinExpr(table=ast.Field(chain=[table_name])),
        where=ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Tuple(
                exprs=[ast.Field(chain=[table_name, "cohort_id"]), ast.Field(chain=[table_name, "version"])]
            ),
            right=ast.Constant(value=cohort_tuples),
        )
        if len(cohort_tuples) > 0
        else ast.Constant(value=False),
    )


class RawCohortPeople(Table):
    fields: dict[str, FieldOrTable] = {
        **COHORT_PEOPLE_FIELDS,
        "sign": IntegerDatabaseField(name="sign", nullable=False),
        "version": IntegerDatabaseField(name="version", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return "cohortpeople"

    def to_printed_hogql(self):
        return "raw_cohort_people"


class CohortPeople(LazyTable):
    fields: dict[str, FieldOrTable] = COHORT_PEOPLE_FIELDS

    def lazy_select(self, table_to_add: LazyTableToAdd, context, node):
        return select_from_cohort_people_table(table_to_add.fields_accessed, context.project_id)

    def to_printed_clickhouse(self, context):
        return "cohortpeople"

    def to_printed_hogql(self):
        return "cohort_people"
