from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    ExpressionField,
    FieldOrTable,
    IntegerDatabaseField,
    MapStringDatabaseField,
    StringDatabaseField,
    Table,
)
from posthog.hogql.parser import parse_expr

from posthog.clickhouse.workload import Workload


class TraceSpansTable(Table):
    description: str = "OpenTelemetry trace spans, one row per span; join to `logs` on `trace_id`/`span_id`."
    workload: Workload | None = Workload.LOGS

    fields: dict[str, FieldOrTable] = {
        "uuid": StringDatabaseField(name="uuid", nullable=False, description="Unique identifier of this span row."),
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "trace_id": StringDatabaseField(
            name="trace_id", nullable=False, description="Identifier of the trace this span belongs to."
        ),
        "span_id": StringDatabaseField(name="span_id", nullable=False, description="Unique identifier of this span."),
        "parent_span_id": StringDatabaseField(
            name="parent_span_id", nullable=False, description="Identifier of the parent span; empty for root spans."
        ),
        # Computed inline from parent_span_id rather than read from the physical `is_root_span`
        # MATERIALIZED column: that column ships via a separate logs-cluster migration, so it can be
        # absent from trace_spans_distributed during a schema rollout. Deriving it here (mirroring the
        # column's own DDL expression) keeps every query path working regardless of migration order.
        "is_root_span": ExpressionField(
            name="is_root_span",
            expr=parse_expr("replaceAll(trimRight(parent_span_id, '='), 'A', '') = ''"),
            description="True if this span has no parent (the trace root).",
        ),
        "name": StringDatabaseField(
            name="name", nullable=False, description="Name of the operation the span represents."
        ),
        "kind": IntegerDatabaseField(
            name="kind",
            nullable=False,
            description="OpenTelemetry span kind (0=unspecified, 1=internal, 2=server, 3=client, 4=producer, 5=consumer).",
        ),
        "timestamp": DateTimeDatabaseField(name="timestamp", nullable=False, description="When the span started."),
        "end_time": DateTimeDatabaseField(name="end_time", nullable=False, description="When the span ended."),
        "observed_timestamp": DateTimeDatabaseField(
            name="observed_timestamp", nullable=False, description="When the collector observed/ingested the span."
        ),
        "duration_nano": IntegerDatabaseField(
            name="duration_nano", nullable=False, description="Span duration in nanoseconds."
        ),
        "status_code": IntegerDatabaseField(
            name="status_code", nullable=False, description="OpenTelemetry status code (0=unset, 1=ok, 2=error)."
        ),
        "service_name": StringDatabaseField(
            name="service_name", nullable=False, description="Name of the service that emitted the span."
        ),
        "resource_attributes": MapStringDatabaseField(
            name="resource_attributes", nullable=False, description="OpenTelemetry resource attributes as a string map."
        ),
        "resource_fingerprint": IntegerDatabaseField(
            name="resource_fingerprint",
            nullable=False,
            description="Hash of the resource attributes, used to group resources.",
        ),
        "attributes": MapStringDatabaseField(
            name="attributes", nullable=False, description="Per-span OpenTelemetry attributes as a string map."
        ),
        "instrumentation_scope": StringDatabaseField(
            name="instrumentation_scope",
            nullable=False,
            description="Instrumentation scope (library/module) that emitted the span.",
        ),
        "time_bucket": DateTimeDatabaseField(
            name="time_bucket", nullable=False, description="Coarse time bucket used for partitioning and filtering."
        ),
    }

    def to_printed_clickhouse(self, context):
        return "trace_spans_distributed"

    def to_printed_hogql(self):
        return "trace_spans"


class TraceAttributesTable(Table):
    description: str = "Distinct trace span attribute key/value pairs with occurrence counts, used to power span attribute autocomplete and faceting."
    workload: Workload | None = Workload.LOGS

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "time_bucket": DateTimeDatabaseField(
            name="time_bucket",
            nullable=False,
            description="Coarse time bucket the attribute counts are aggregated over.",
        ),
        "attribute_key": StringDatabaseField(name="attribute_key", nullable=False, description="Span attribute name."),
        "attribute_value": StringDatabaseField(
            name="attribute_value", nullable=False, description="Observed value for the attribute key."
        ),
        "attribute_type": StringDatabaseField(
            name="attribute_type",
            nullable=False,
            description="Where the attribute came from (e.g. resource vs span attribute).",
        ),
        "attribute_count": IntegerDatabaseField(
            name="attribute_count",
            nullable=False,
            description="Number of spans with this key/value in the time bucket.",
        ),
        "resource_fingerprint": IntegerDatabaseField(
            name="resource_fingerprint",
            nullable=False,
            description="Hash of the resource attributes the count is scoped to.",
        ),
        "service_name": StringDatabaseField(
            name="service_name", nullable=False, description="Service the attribute counts are scoped to."
        ),
    }

    def to_printed_clickhouse(self, context):
        return "trace_attributes_distributed"

    def to_printed_hogql(self):
        return "trace_attributes"
