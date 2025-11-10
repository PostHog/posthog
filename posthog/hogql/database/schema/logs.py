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
        "time_bucket": DateTimeDatabaseField(name="time_bucket", nullable=False),
        "time_minute": DateTimeDatabaseField(name="time_minute", nullable=False),
        "timestamp": DateTimeDatabaseField(name="timestamp", nullable=False),
        "observed_timestamp": DateTimeDatabaseField(name="observed_timestamp", nullable=False),
        "severity_text": StringDatabaseField(name="severity_text", nullable=False),
        "severity_number": IntegerDatabaseField(name="severity_number", nullable=False),
        "level": StringDatabaseField(name="level", nullable=False),
        "resource_attributes": StringJSONDatabaseField(name="resource_attributes", nullable=False),
        "resource_fingerprint": IntegerDatabaseField(name="resource_fingerprint", nullable=False),
        "instrumentation_scope": StringDatabaseField(name="instrumentation_scope", nullable=False),
        "event_name": StringDatabaseField(name="event_name", nullable=False),
        "service_name": StringDatabaseField(name="service_name", nullable=False),
        # internal fields for query optimization
        "_part": StringDatabaseField(name="_part", nullable=True, hidden=True),
        "_part_starting_offset": IntegerDatabaseField(name="_part_starting_offset", nullable=True, hidden=True),
        "_part_offset": IntegerDatabaseField(name="_part_offset", nullable=True, hidden=True),
        "mat_body_ipv4_matches": StringJSONDatabaseField(name="mat_body_ipv4_matches", nullable=True, hidden=True),
    }

    def to_printed_clickhouse(self, context):
        return "logs29"

    def to_printed_hogql(self):
        return "logs29"


class LogAttributesTable(Table):
    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "time_bucket": DateTimeDatabaseField(name="time_bucket", nullable=False),
        "attribute_key": StringDatabaseField(name="attribute_key", nullable=False),
        "attribute_value": StringDatabaseField(name="attribute_value", nullable=False),
        "resource_fingerprint": IntegerDatabaseField(name="resource_fingerprint", nullable=False),
        "service_name": StringDatabaseField(name="service_name", nullable=False)
    }

    def to_printed_clickhouse(self, context):
        return "log_attributes"

    def to_printed_hogql(self):
        return "log_attributes"
