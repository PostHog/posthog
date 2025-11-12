from posthog.hogql.database.models import (
    DateDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
)


class PrecalculatedEventsTable(Table):
    """Table for precalculated behavioral events populated by CdpBehaviouralEventsConsumer."""

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "distinct_id": StringDatabaseField(name="distinct_id", nullable=False),
        "condition": StringDatabaseField(name="condition", nullable=False),
        "date": DateDatabaseField(name="date", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return "precalculated_events"

    def to_printed_hogql(self):
        return "precalculated_events"
