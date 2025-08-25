from posthog.hogql.database.models import FieldOrTable, IntegerDatabaseField, LazyJoin, StringDatabaseField, Table
from posthog.hogql.database.schema.persons import join_with_persons_table


class StaticCohortPeople(Table):
    fields: dict[str, FieldOrTable] = {
        "person_id": StringDatabaseField(name="person_id", nullable=False),
        "cohort_id": IntegerDatabaseField(name="cohort_id", nullable=False),
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "person": LazyJoin(
            from_field=["person_id"],
            join_table="persons",
            join_function=join_with_persons_table,
        ),
    }

    def avoid_asterisk_fields(self):
        return ["_timestamp", "_offset"]

    def to_printed_clickhouse(self, context):
        return "person_static_cohort"

    def to_printed_hogql(self):
        return "static_cohort_people"
