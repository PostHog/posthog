from posthog.hogql.database.models import (
    DateDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
    UUIDDatabaseField,
)


class PrecalculatedEventsTable(Table):
    """Table for precalculated behavioral events populated by CdpRealtimeCohortsConsumer."""

    description: str = (
        "Internal cache of behavioral matches used by realtime cohort calculation: records that a person "
        "satisfied a cohort behavioral condition on a given date. Populated by the realtime cohorts consumer; "
        "not a general analytics table."
    )

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "distinct_id": StringDatabaseField(
            name="distinct_id", nullable=False, description="Distinct ID that triggered the matching behavioral event."
        ),
        "person_id": UUIDDatabaseField(
            name="person_id",
            nullable=False,
            description="Person the matching event is attributed to; join to `persons.id`.",
        ),
        "condition": StringDatabaseField(
            name="condition",
            nullable=False,
            description="Identifier of the cohort behavioral condition that was matched.",
        ),
        "date": DateDatabaseField(
            name="date", nullable=False, description="Date on which the behavioral condition was matched."
        ),
        "uuid": UUIDDatabaseField(
            name="uuid", nullable=False, description="UUID of the underlying event that produced this match."
        ),
        "source": StringDatabaseField(
            name="source",
            nullable=False,
            description="Origin of this precalculated row (e.g. realtime ingestion vs backfill).",
        ),
        "_timestamp": DateTimeDatabaseField(name="_timestamp", nullable=False),
        "_partition": IntegerDatabaseField(name="_partition", nullable=False),
        "_offset": IntegerDatabaseField(name="_offset", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return "precalculated_events"

    def to_printed_hogql(self):
        return "precalculated_events"
