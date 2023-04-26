from typing import Dict, Any, List

from posthog.hogql.database.models import StringDatabaseField, IntegerDatabaseField, Table, LazyJoin, LazyTable
from posthog.hogql.database.schema.persons import PersonsTable, join_with_persons_table
from posthog.hogql.parser import parse_expr


def select_from_cohort_people_table(requested_fields: Dict[str, Any]):
    from posthog.hogql import ast

    if not requested_fields:
        requested_fields = {}
    if "person_id" not in requested_fields:
        requested_fields["person_id"] = ast.Field(chain=["person_id"])
    if "cohort_id" not in requested_fields:
        requested_fields["cohort_id"] = ast.Field(chain=["cohort_id"])

    fields: List[ast.Expr] = [expr for expr in requested_fields.values()]

    return ast.SelectQuery(
        select=fields,
        select_from=ast.JoinExpr(table=ast.Field(chain=["raw_cohort_people"])),
        group_by=fields,
        having=parse_expr("sum(sign) > 0"),
    )


class RawCohortPeople(Table):
    person_id: StringDatabaseField = StringDatabaseField(name="person_id")
    cohort_id: IntegerDatabaseField = IntegerDatabaseField(name="cohort_id")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    sign: IntegerDatabaseField = IntegerDatabaseField(name="sign")
    version: IntegerDatabaseField = IntegerDatabaseField(name="version")

    person: LazyJoin = LazyJoin(
        from_field="person_id", join_table=PersonsTable(), join_function=join_with_persons_table
    )

    def clickhouse_table(self):
        return "cohortpeople"

    def hogql_table(self):
        return "cohort_people"


class CohortPeople(LazyTable):
    person_id: StringDatabaseField = StringDatabaseField(name="person_id")
    cohort_id: IntegerDatabaseField = IntegerDatabaseField(name="cohort_id")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")

    person: LazyJoin = LazyJoin(
        from_field="person_id", join_table=PersonsTable(), join_function=join_with_persons_table
    )

    def lazy_select(self, requested_fields: Dict[str, Any]):
        return select_from_cohort_people_table(requested_fields)

    def clickhouse_table(self):
        return "cohortpeople"

    def hogql_table(self):
        return "cohort_people"
