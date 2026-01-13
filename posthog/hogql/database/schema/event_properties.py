from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
)


class EventPropertiesTable(Table):
    """EAV table for event properties materialization.

    Note: DateTime properties use value_string (not a separate column) to match
    traditional mat_* column behavior. This avoids timezone interpretation issues.
    """

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "timestamp": DateTimeDatabaseField(name="timestamp", nullable=False),
        "event": StringDatabaseField(name="event", nullable=False),
        "distinct_id": StringDatabaseField(name="distinct_id", nullable=False),
        "uuid": StringDatabaseField(name="uuid", nullable=False),
        "key": StringDatabaseField(name="key", nullable=False),
        "value_string": StringDatabaseField(name="value_string", nullable=True),
        "value_numeric": FloatDatabaseField(name="value_numeric", nullable=True),
        "value_bool": IntegerDatabaseField(name="value_bool", nullable=True),
    }

    def to_printed_clickhouse(self, context):
        return "event_properties"

    def to_printed_hogql(self):
        return "event_properties"
