from typing import Dict

from posthog.hogql.database.models import (
    Table,
    StringDatabaseField,
    IntegerDatabaseField,
    LazyJoin,
    FieldOrTable,
)
from posthog.hogql.database.schema.persons import PersonsTable, join_with_persons_table


class StaticCohortPeople(Table):
    fields: Dict[str, FieldOrTable] = {
        "person_id": StringDatabaseField(name="person_id"),
        "cohort_id": IntegerDatabaseField(name="cohort_id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "person": LazyJoin(
            from_field="person_id",
            join_table=PersonsTable(),
            join_function=join_with_persons_table,
        ),
    }

    def avoid_asterisk_fields(self):
        return ["_timestamp", "_offset"]

    def to_printed_clickhouse(self, context):
        return "person_static_cohort"

    def to_printed_hogql(self):
        return "static_cohort_people"
