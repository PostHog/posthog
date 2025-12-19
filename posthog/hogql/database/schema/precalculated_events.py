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

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "distinct_id": StringDatabaseField(name="distinct_id", nullable=False),
        "person_id": UUIDDatabaseField(name="person_id", nullable=False),
        "condition": StringDatabaseField(name="condition", nullable=False),
        "date": DateDatabaseField(name="date", nullable=False),
        "uuid": UUIDDatabaseField(name="uuid", nullable=False),
        "source": StringDatabaseField(name="source", nullable=False),
        "_timestamp": DateTimeDatabaseField(name="_timestamp", nullable=False),
        "_partition": IntegerDatabaseField(name="_partition", nullable=False),
        "_offset": IntegerDatabaseField(name="_offset", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return "precalculated_events"

    def to_printed_hogql(self):
        return "precalculated_events"
