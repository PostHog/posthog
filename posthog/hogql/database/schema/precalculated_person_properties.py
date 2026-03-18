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

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "distinct_id": StringDatabaseField(name="distinct_id", nullable=False),
        "person_id": UUIDDatabaseField(name="person_id", nullable=False),
        "condition": StringDatabaseField(name="condition", nullable=False),
        "matches": BooleanDatabaseField(name="matches", nullable=False),
        "source": StringDatabaseField(name="source", nullable=False),
        "_timestamp": DateTimeDatabaseField(name="_timestamp", nullable=False),
        "_offset": IntegerDatabaseField(name="_offset", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return "precalculated_person_properties"

    def to_printed_hogql(self):
        return "precalculated_person_properties"
