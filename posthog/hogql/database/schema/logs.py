from posthog.hogql.database.models import (
    DANGEROUS_NoTeamIdCheckTable,
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    MapStringDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
)

from posthog.clickhouse.workload import Workload

# 50GB - limit for user-provided HogQL queries on log tables to prevent expensive full scans
HOGQL_MAX_BYTES_TO_READ_FOR_LOGS_USER_QUERIES = 50_000_000_000


class LogsTable(Table):
    description: str = "OpenTelemetry-style log records ingested into the logs product, one row per log line."
    workload: Workload | None = Workload.LOGS

    fields: dict[str, FieldOrTable] = {
        "uuid": StringDatabaseField(name="uuid", nullable=False, description="Unique identifier of this log record."),
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "trace_id": StringDatabaseField(
            name="trace_id",
            nullable=False,
            description="Trace this log belongs to; join to `trace_spans` on `trace_id`.",
        ),
        "span_id": StringDatabaseField(
            name="span_id", nullable=False, description="Span this log was emitted within; join to `trace_spans`."
        ),
        "message": StringDatabaseField(
            name="body", nullable=False, description="The log message text; alias of `body`."
        ),
        "body": StringDatabaseField(name="body", nullable=False, description="The raw log message text."),
        "attributes": MapStringDatabaseField(
            name="attributes", nullable=False, description="Per-record OpenTelemetry log attributes as a string map."
        ),
        "time_bucket": DateTimeDatabaseField(
            name="time_bucket", nullable=False, description="Coarse time bucket used for partitioning and filtering."
        ),
        "timestamp": DateTimeDatabaseField(
            name="timestamp", nullable=False, description="When the log event occurred (event timestamp)."
        ),
        "observed_timestamp": DateTimeDatabaseField(
            name="observed_timestamp",
            nullable=False,
            description="When the collector observed/ingested the log; differs from `timestamp`.",
        ),
        "severity_text": StringDatabaseField(
            name="severity_text", nullable=False, description="OpenTelemetry severity text, e.g. 'INFO', 'ERROR'."
        ),
        "severity_number": IntegerDatabaseField(
            name="severity_number",
            nullable=False,
            description="OpenTelemetry numeric severity (1-24, higher is more severe).",
        ),
        "level": StringDatabaseField(
            name="level", nullable=False, description="Normalized log level, e.g. 'info', 'warn', 'error'."
        ),
        "resource_attributes": MapStringDatabaseField(
            name="resource_attributes",
            nullable=False,
            description="OpenTelemetry resource attributes (the emitting service/host) as a string map.",
        ),
        "resource_fingerprint": IntegerDatabaseField(
            name="resource_fingerprint",
            nullable=False,
            description="Hash of the resource attributes, used to deduplicate/group resources.",
        ),
        "instrumentation_scope": StringDatabaseField(
            name="instrumentation_scope",
            nullable=False,
            description="OpenTelemetry instrumentation scope (library/module that emitted the log).",
        ),
        "event_name": StringDatabaseField(
            name="event_name", nullable=False, description="OpenTelemetry log event name, when set."
        ),
        "service_name": StringDatabaseField(
            name="service_name", nullable=False, description="Name of the service that emitted the log."
        ),
        # internal fields for query optimization
        "_part_starting_offset": IntegerDatabaseField(name="_part_starting_offset", nullable=True, hidden=True),
        "_part_offset": IntegerDatabaseField(name="_part_offset", nullable=True, hidden=True),
        "_bytes_uncompressed": IntegerDatabaseField(name="_bytes_uncompressed", nullable=True, hidden=True),
        "mat_body_ipv4_matches": StringJSONDatabaseField(name="mat_body_ipv4_matches", nullable=True, hidden=True),
    }

    def to_printed_clickhouse(self, context):
        return "logs_distributed"

    def to_printed_hogql(self):
        return "logs"


class LogAttributesTable(Table):
    description: str = "Distinct log attribute key/value pairs with occurrence counts, used to power log attribute autocomplete and faceting."
    workload: Workload | None = Workload.LOGS
    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "time_bucket": DateTimeDatabaseField(
            name="time_bucket",
            nullable=False,
            description="Coarse time bucket the attribute counts are aggregated over.",
        ),
        "attribute_key": StringDatabaseField(name="attribute_key", nullable=False, description="Log attribute name."),
        "attribute_value": StringDatabaseField(
            name="attribute_value", nullable=False, description="Observed value for the attribute key."
        ),
        "attribute_type": StringDatabaseField(
            name="attribute_type",
            nullable=False,
            description="Where the attribute came from (e.g. resource vs log attribute).",
        ),
        "attribute_count": IntegerDatabaseField(
            name="attribute_count", nullable=False, description="Number of logs with this key/value in the time bucket."
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
        return "log_attributes_distributed"

    def to_printed_hogql(self):
        return "log_attributes"


class LogsKafkaMetricsTable(DANGEROUS_NoTeamIdCheckTable):
    """
    Table stores meta information about kafka consumption _not_ scoped to teams

    This is so we can find out the overall lag per partition and filter live logs accordingly
    """

    description: str = "Per-partition Kafka consumption metadata for the logs ingestion topic; not scoped to teams, used to track ingestion lag."
    workload: Workload | None = Workload.LOGS
    fields: dict[str, FieldOrTable] = {
        "_partition": IntegerDatabaseField(name="_partition", nullable=False),
        "_topic": StringDatabaseField(name="_topic", nullable=False),
        "max_observed_timestamp": DateTimeDatabaseField(
            name="max_observed_timestamp",
            nullable=False,
            description="Latest observed timestamp consumed from this partition; used to compute ingestion lag.",
        ),
    }

    def to_printed_clickhouse(self, context):
        return "logs_kafka_metrics_distributed"

    def to_printed_hogql(self):
        return "logs_kafka_metrics"
