from posthog.hogql.database.models import StringDatabaseField, IntegerDatabaseField, Table, LazyJoin
from posthog.hogql.database.schema.persons import PersonsTable, join_with_persons_table


class CohortPeople(Table):
    person_id: StringDatabaseField = StringDatabaseField(name="person_id")
    cohort_id: IntegerDatabaseField = IntegerDatabaseField(name="cohort_id")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    sign: IntegerDatabaseField = IntegerDatabaseField(name="sign")
    version: IntegerDatabaseField = IntegerDatabaseField(name="version")

    # TODO: automatically add "HAVING SUM(sign) > 0" to fields selected from this table?

    person: LazyJoin = LazyJoin(
        from_field="person_id", join_table=PersonsTable(), join_function=join_with_persons_table
    )

    def clickhouse_table(self):
        return "cohortpeople"

    def hogql_table(self):
        return "cohort_people"
