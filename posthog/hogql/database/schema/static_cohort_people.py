from posthog.hogql.database.lazy_join_tags import PERSONS
from posthog.hogql.database.models import FieldOrTable, IntegerDatabaseField, LazyJoin, StringDatabaseField, Table


class StaticCohortPeople(Table):
    description: str = (
        "Membership of static cohorts — fixed lists of people (e.g. CSV-imported) that are not recalculated. "
        "One row per person per cohort. Dynamic (calculated) cohorts live in `cohort_people`."
    )
    fields: dict[str, FieldOrTable] = {
        "person_id": StringDatabaseField(
            name="person_id", nullable=False, description="Person who is a member of the cohort; join to `persons.id`."
        ),
        "cohort_id": IntegerDatabaseField(
            name="cohort_id", nullable=False, description="Identifier of the static cohort this person belongs to."
        ),
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "person": LazyJoin(
            from_field=["person_id"],
            join_table="persons",
            resolver=PERSONS,
        ),
    }

    def avoid_asterisk_fields(self):
        return ["_timestamp", "_offset"]

    def to_printed_clickhouse(self, context):
        return "person_static_cohort"

    def to_printed_hogql(self):
        return "static_cohort_people"
