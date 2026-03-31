from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
)

from posthog.clickhouse.workload import Workload


class TraceSpansTable(Table):
    workload: Workload | None = Workload.LOGS

    fields: dict[str, FieldOrTable] = {
        "uuid": StringDatabaseField(name="uuid", nullable=False),
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "trace_id": StringDatabaseField(name="trace_id", nullable=False),
        "span_id": StringDatabaseField(name="span_id", nullable=False),
        "parent_span_id": StringDatabaseField(name="parent_span_id", nullable=False),
        "is_root_span": BooleanDatabaseField(name="is_root_span", nullable=False),
        "name": StringDatabaseField(name="name", nullable=False),
        "kind": IntegerDatabaseField(name="kind", nullable=False),
        "timestamp": DateTimeDatabaseField(name="timestamp", nullable=False),
        "end_time": DateTimeDatabaseField(name="end_time", nullable=False),
        "observed_timestamp": DateTimeDatabaseField(name="observed_timestamp", nullable=False),
        "duration_nano": IntegerDatabaseField(name="duration_nano", nullable=False),
        "status_code": IntegerDatabaseField(name="status_code", nullable=False),
        "service_name": StringDatabaseField(name="service_name", nullable=False),
        "resource_attributes": StringJSONDatabaseField(name="resource_attributes", nullable=False),
        "resource_fingerprint": IntegerDatabaseField(name="resource_fingerprint", nullable=False),
        "attributes": StringJSONDatabaseField(name="attributes", nullable=False),
        "instrumentation_scope": StringDatabaseField(name="instrumentation_scope", nullable=False),
        "time_bucket": DateTimeDatabaseField(name="time_bucket", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return "trace_spans"

    def to_printed_hogql(self):
        return "trace_spans"


class TraceAttributesTable(Table):
    workload: Workload | None = Workload.LOGS

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "time_bucket": DateTimeDatabaseField(name="time_bucket", nullable=False),
        "attribute_key": StringDatabaseField(name="attribute_key", nullable=False),
        "attribute_value": StringDatabaseField(name="attribute_value", nullable=False),
        "attribute_type": StringDatabaseField(name="attribute_type", nullable=False),
        "attribute_count": IntegerDatabaseField(name="attribute_count", nullable=False),
        "resource_fingerprint": IntegerDatabaseField(name="resource_fingerprint", nullable=False),
        "service_name": StringDatabaseField(name="service_name", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return "trace_attributes"

    def to_printed_hogql(self):
        return "trace_attributes"
