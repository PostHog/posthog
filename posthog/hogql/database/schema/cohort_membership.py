from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
    UUIDDatabaseField,
)


class CohortMembershipTable(Table):
    """Table tracking realtime cohort membership changes."""

    description: str = (
        "Realtime cohort membership changes, one row per person per cohort kept at its latest state. "
        "Records when a person enters or leaves a cohort, as evaluated by the realtime cohorts pipeline."
    )

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "cohort_id": IntegerDatabaseField(
            name="cohort_id", nullable=False, description="Identifier of the cohort whose membership changed."
        ),
        "person_id": UUIDDatabaseField(
            name="person_id", nullable=False, description="Person whose membership changed; join to `persons.id`."
        ),
        "status": StringDatabaseField(
            name="status",
            nullable=False,
            description="Latest membership status for this person/cohort: 'entered' or 'left'.",
        ),
        "last_updated": DateTimeDatabaseField(
            name="last_updated", nullable=False, description="When this membership status was last updated (UTC)."
        ),
    }

    def to_printed_clickhouse(self, context):
        return "cohort_membership"

    def to_printed_hogql(self):
        return "cohort_membership"
