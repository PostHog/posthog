from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
    UUIDDatabaseField,
)


class PrecalculatedPersonPropertiesTable(Table):
    """Table for precalculated person properties evaluations populated by CdpRealtimeCohortsConsumer."""

    description: str = (
        "Internal cache of person-property condition evaluations used by realtime cohort calculation: "
        "whether a person matched a cohort's property condition. Populated by the realtime cohorts consumer; "
        "not a general analytics table."
    )

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "distinct_id": StringDatabaseField(
            name="distinct_id",
            nullable=False,
            description="Distinct ID for which the property condition was evaluated.",
        ),
        "person_id": UUIDDatabaseField(
            name="person_id",
            nullable=False,
            description="Person the evaluation is attributed to; join to `persons.id`.",
        ),
        "condition": StringDatabaseField(
            name="condition",
            nullable=False,
            description="Identifier of the cohort person-property condition that was evaluated.",
        ),
        "matches": BooleanDatabaseField(
            name="matches", nullable=False, description="True if the person satisfied the property condition."
        ),
        "source": StringDatabaseField(
            name="source",
            nullable=False,
            description="Origin of this precalculated row (e.g. realtime ingestion vs backfill).",
        ),
        "_timestamp": DateTimeDatabaseField(name="_timestamp", nullable=False),
        "_offset": IntegerDatabaseField(name="_offset", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return "precalculated_person_properties"

    def to_printed_hogql(self):
        return "precalculated_person_properties"
