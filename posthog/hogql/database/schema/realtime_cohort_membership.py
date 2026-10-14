from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
    UUIDDatabaseField,
)


class RealtimeCohortMembershipTable(Table):
    description: str = (
        "Realtime cohort membership, copied from the realtime cohorts pipeline. One row per change, "
        "so the current status of a person in a cohort is argMax(status, last_updated)."
    )

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "cohort_id": IntegerDatabaseField(name="cohort_id", nullable=False, description="The realtime cohort."),
        "person_id": UUIDDatabaseField(
            name="person_id", nullable=False, description="The person whose membership changed; join to `persons.id`."
        ),
        "status": StringDatabaseField(
            name="status", nullable=False, description="'entered' or 'left' as of `last_updated`."
        ),
        "last_updated": DateTimeDatabaseField(
            name="last_updated",
            nullable=False,
            description="The version of the change. The latest one is the current status (UTC).",
        ),
        "origin": StringDatabaseField(
            name="origin",
            nullable=False,
            description="Empty for a live change; 'seed', 'reconcile', 'sweep' or 'backfill' otherwise.",
        ),
    }

    def to_printed_clickhouse(self, context):
        return "realtime_cohort_membership"

    def to_printed_hogql(self):
        return "realtime_cohort_membership"
