from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DANGEROUS_NoTeamIdCheckTable,
    DateTimeDatabaseField,
    FieldOrTable,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
)

from posthog.clickhouse.workload import Workload

# 50GB - limit for user-provided HogQL queries on metrics tables to prevent expensive full scans
HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES = 50_000_000_000


class MetricsTable(Table):
    workload: Workload | None = Workload.LOGS  # reuse LOGS workload for now

    fields: dict[str, FieldOrTable] = {
        "uuid": StringDatabaseField(name="uuid", nullable=False),
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "trace_id": StringDatabaseField(name="trace_id", nullable=False),
        "span_id": StringDatabaseField(name="span_id", nullable=False),
        "time_bucket": DateTimeDatabaseField(name="time_bucket", nullable=False),
        "timestamp": DateTimeDatabaseField(name="timestamp", nullable=False),
        "observed_timestamp": DateTimeDatabaseField(name="observed_timestamp", nullable=False),
        "service_name": StringDatabaseField(name="service_name", nullable=False),
        "metric_name": StringDatabaseField(name="metric_name", nullable=False),
        "metric_type": StringDatabaseField(name="metric_type", nullable=False),
        "value": FloatDatabaseField(name="value", nullable=False),
        "count": IntegerDatabaseField(name="count", nullable=False),
        "histogram_bounds": StringJSONDatabaseField(name="histogram_bounds", nullable=False),
        "histogram_counts": StringJSONDatabaseField(name="histogram_counts", nullable=False),
        "unit": StringDatabaseField(name="unit", nullable=False),
        "aggregation_temporality": StringDatabaseField(name="aggregation_temporality", nullable=False),
        "is_monotonic": BooleanDatabaseField(name="is_monotonic", nullable=False),
        "resource_attributes": StringJSONDatabaseField(name="resource_attributes", nullable=False),
        "resource_fingerprint": IntegerDatabaseField(name="resource_fingerprint", nullable=False),
        "instrumentation_scope": StringDatabaseField(name="instrumentation_scope", nullable=False),
        "attributes": StringJSONDatabaseField(name="attributes", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return "metrics"

    def to_printed_hogql(self):
        return "metrics"


class MetricAttributesTable(Table):
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
        return "metric_attributes"

    def to_printed_hogql(self):
        return "metric_attributes"


class MetricsKafkaMetricsTable(DANGEROUS_NoTeamIdCheckTable):
    """
    Table stores meta information about kafka consumption _not_ scoped to teams

    This is so we can find out the overall lag per partition and filter live metrics accordingly
    """

    workload: Workload | None = Workload.LOGS

    fields: dict[str, FieldOrTable] = {
        "_partition": IntegerDatabaseField(name="_partition", nullable=False),
        "_topic": StringDatabaseField(name="_topic", nullable=False),
        "max_observed_timestamp": DateTimeDatabaseField(name="max_observed_timestamp", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return "metrics_kafka_metrics"

    def to_printed_hogql(self):
        return "metrics_kafka_metrics"
