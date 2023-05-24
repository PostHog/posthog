from posthog.hogql.database.models import Table, StringDatabaseField, IntegerDatabaseField, LazyJoin
from posthog.hogql.database.schema.persons import PersonsTable, join_with_persons_table


class StaticCohortPeople(Table):
    person_id: StringDatabaseField = StringDatabaseField(name="person_id")
    cohort_id: IntegerDatabaseField = IntegerDatabaseField(name="cohort_id")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")

    person: LazyJoin = LazyJoin(
        from_field="person_id", join_table=PersonsTable(), join_function=join_with_persons_table
    )

    def avoid_asterisk_fields(self):
        return ["_timestamp", "_offset"]

    def clickhouse_table(self):
        return "person_static_cohort"

    def hogql_table(self):
        return "static_cohort_people"
