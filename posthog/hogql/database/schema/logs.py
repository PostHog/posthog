from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
)


class LogsTable(Table):
    fields: dict[str, FieldOrTable] = {
        "uuid": StringDatabaseField(name="uuid", nullable=False),
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "trace_id": StringDatabaseField(name="trace_id", nullable=False),
        "span_id": StringDatabaseField(name="span_id", nullable=False),
        "body": StringDatabaseField(name="body", nullable=False),
        "attributes": StringJSONDatabaseField(name="attributes", nullable=False),
        "timestamp": DateTimeDatabaseField(name="timestamp", nullable=False),
        "observed_timestamp": DateTimeDatabaseField(name="observed_timestamp", nullable=False),
        "severity_text": StringDatabaseField(name="severity_text", nullable=False),
        "severity_number": IntegerDatabaseField(name="severity_number", nullable=False),
        "level": StringDatabaseField(name="level", nullable=False),
        "resource_attributes": StringJSONDatabaseField(name="resource_attributes", nullable=False),
        "instrumentation_scope": StringDatabaseField(name="instrumentation_scope", nullable=False),
        "event_name": StringDatabaseField(name="event_name", nullable=False),
        "service_name": StringDatabaseField(name="service_name", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return "logs"

    def to_printed_hogql(self):
        return "logs"
