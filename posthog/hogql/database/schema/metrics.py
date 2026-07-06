from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DANGEROUS_NoTeamIdCheckTable,
    DateTimeDatabaseField,
    FieldOrTable,
    FloatDatabaseField,
    IntegerDatabaseField,
    MapStringDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
)

from posthog.clickhouse.workload import Workload

# 50GB - limit for user-provided HogQL queries on metrics tables to prevent expensive full scans
HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES = 50_000_000_000


class MetricsTable(Table):
    description: str = "OpenTelemetry metric data points (gauges, sums, histograms), one row per data point."
    workload: Workload | None = Workload.LOGS  # reuse LOGS workload for now

    fields: dict[str, FieldOrTable] = {
        "uuid": StringDatabaseField(
            name="uuid", nullable=False, description="Unique identifier of this data point row."
        ),
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "trace_id": StringDatabaseField(
            name="trace_id", nullable=False, description="Trace this metric exemplar is associated with, if any."
        ),
        "span_id": StringDatabaseField(
            name="span_id", nullable=False, description="Span this metric exemplar is associated with, if any."
        ),
        "time_bucket": DateTimeDatabaseField(
            name="time_bucket", nullable=False, description="Coarse time bucket used for partitioning and filtering."
        ),
        "timestamp": DateTimeDatabaseField(
            name="timestamp", nullable=False, description="When the metric data point was recorded."
        ),
        "observed_timestamp": DateTimeDatabaseField(
            name="observed_timestamp",
            nullable=False,
            description="When the collector observed/ingested the data point.",
        ),
        "service_name": StringDatabaseField(
            name="service_name", nullable=False, description="Name of the service that emitted the metric."
        ),
        "metric_name": StringDatabaseField(name="metric_name", nullable=False, description="Name of the metric."),
        "metric_type": StringDatabaseField(
            name="metric_type",
            nullable=False,
            description="OpenTelemetry metric type, e.g. 'gauge', 'sum', 'histogram'.",
        ),
        "value": FloatDatabaseField(
            name="value", nullable=False, description="Numeric value of the data point (for gauge/sum metrics)."
        ),
        "count": IntegerDatabaseField(
            name="count", nullable=False, description="Total count of observations (for histogram metrics)."
        ),
        "histogram_bounds": StringJSONDatabaseField(
            name="histogram_bounds", nullable=False, description="JSON array of histogram bucket boundaries."
        ),
        "histogram_counts": StringJSONDatabaseField(
            name="histogram_counts",
            nullable=False,
            description="JSON array of per-bucket counts, aligned with `histogram_bounds`.",
        ),
        "unit": StringDatabaseField(
            name="unit", nullable=False, description="Unit of the metric value, e.g. 'ms', 'By'."
        ),
        "aggregation_temporality": StringDatabaseField(
            name="aggregation_temporality",
            nullable=False,
            description="OpenTelemetry temporality, e.g. 'delta' or 'cumulative'.",
        ),
        "is_monotonic": BooleanDatabaseField(
            name="is_monotonic", nullable=False, description="True if the sum metric only increases."
        ),
        "resource_attributes": MapStringDatabaseField(
            name="resource_attributes", nullable=False, description="OpenTelemetry resource attributes as a string map."
        ),
        "resource_fingerprint": IntegerDatabaseField(
            name="resource_fingerprint",
            nullable=False,
            description="Hash of the resource attributes, used to group resources.",
        ),
        "instrumentation_scope": StringDatabaseField(
            name="instrumentation_scope",
            nullable=False,
            description="Instrumentation scope (library/module) that emitted the metric.",
        ),
        "attributes": MapStringDatabaseField(
            name="attributes", nullable=False, description="Per-data-point OpenTelemetry attributes as a string map."
        ),
    }

    def to_printed_clickhouse(self, context):
        return "metrics"

    def to_printed_hogql(self):
        return "metrics"


class MetricSamplesTable(Table):
    description: str = "Raw metric emissions: one tiny row per sample (value + timestamp), keyed to a series via `series_fingerprint` and carrying an optional `trace_id` for the metric->trace pivot. Join to `metric_series` for labels. Distinct from `metrics`, which is pre-aggregated."
    workload: Workload | None = Workload.LOGS

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "metric_name": StringDatabaseField(name="metric_name", nullable=False),
        "series_fingerprint": IntegerDatabaseField(
            name="series_fingerprint",
            nullable=False,
            description="Hash of the series' label set; join key to `metric_series`.",
        ),
        "timestamp": DateTimeDatabaseField(
            name="timestamp", nullable=False, description="When the metric was emitted (UTC)."
        ),
        "value": FloatDatabaseField(
            name="value",
            nullable=False,
            description="The emitted value. For histogram/summary points this is the distribution sum; pair with `count`.",
        ),
        "count": IntegerDatabaseField(
            name="count",
            nullable=False,
            description="Observations behind this point: 1 for gauges/counters, the distribution count for histograms/summaries.",
        ),
        "histogram_bounds": StringJSONDatabaseField(
            name="histogram_bounds",
            nullable=False,
            description="Histogram bucket boundaries; empty for non-histograms.",
        ),
        "histogram_counts": StringJSONDatabaseField(
            name="histogram_counts",
            nullable=False,
            description="Per-bucket counts, aligned with `histogram_bounds`; empty for non-histograms.",
        ),
        "trace_id": StringDatabaseField(
            name="trace_id",
            nullable=False,
            description="Trace this emission belongs to; empty if none. Pivot to spans/logs.",
        ),
        "span_id": StringDatabaseField(name="span_id", nullable=False),
        "trace_flags": IntegerDatabaseField(name="trace_flags", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return "metric_samples"

    def to_printed_hogql(self):
        return "metric_samples"


class MetricSeriesTable(Table):
    description: str = "One row per unique metric series (metric + label set), keyed by `series_fingerprint`. Labels are stored here once and joined to `metric_samples` at query time."
    workload: Workload | None = Workload.LOGS

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "metric_name": StringDatabaseField(name="metric_name", nullable=False),
        "series_fingerprint": IntegerDatabaseField(
            name="series_fingerprint",
            nullable=False,
            description="Hash of the label set; join key from `metric_samples`.",
        ),
        "metric_type": StringDatabaseField(
            name="metric_type",
            nullable=False,
            description="OTel metric type (gauge, sum, histogram, summary, exponential_histogram).",
        ),
        "unit": StringDatabaseField(name="unit", nullable=False),
        "aggregation_temporality": StringDatabaseField(
            name="aggregation_temporality",
            nullable=False,
            description="For counters: 'delta' or 'cumulative'. Decides whether rate() must diff. Empty for gauges.",
        ),
        "is_monotonic": BooleanDatabaseField(
            name="is_monotonic", nullable=False, description="True for monotonically increasing counters."
        ),
        "service_name": StringDatabaseField(name="service_name", nullable=False),
        "resource_attributes": MapStringDatabaseField(name="resource_attributes", nullable=False),
        "attributes": MapStringDatabaseField(name="attributes", nullable=False),
        "last_seen": DateTimeDatabaseField(
            name="last_seen", nullable=False, description="Most recent sample timestamp seen for this series."
        ),
    }

    def to_printed_clickhouse(self, context):
        return "metric_series"

    def to_printed_hogql(self):
        return "metric_series"


class MetricAttributesTable(Table):
    description: str = "Distinct metric attribute key/value pairs with occurrence counts, used to power metric attribute autocomplete and faceting."
    workload: Workload | None = Workload.LOGS

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "time_bucket": DateTimeDatabaseField(
            name="time_bucket",
            nullable=False,
            description="Coarse time bucket the attribute counts are aggregated over.",
        ),
        "attribute_key": StringDatabaseField(
            name="attribute_key", nullable=False, description="Metric attribute name."
        ),
        "attribute_value": StringDatabaseField(
            name="attribute_value", nullable=False, description="Observed value for the attribute key."
        ),
        "attribute_type": StringDatabaseField(
            name="attribute_type",
            nullable=False,
            description="Where the attribute came from (e.g. resource vs metric attribute).",
        ),
        "attribute_count": IntegerDatabaseField(
            name="attribute_count",
            nullable=False,
            description="Number of data points with this key/value in the time bucket.",
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
        return "metric_attributes"

    def to_printed_hogql(self):
        return "metric_attributes"


class MetricsKafkaMetricsTable(DANGEROUS_NoTeamIdCheckTable):
    """
    Table stores meta information about kafka consumption _not_ scoped to teams

    This is so we can find out the overall lag per partition and filter live metrics accordingly
    """

    description: str = "Per-partition Kafka consumption metadata for the metrics ingestion topic; not scoped to teams, used to track ingestion lag."
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
        return "metrics_kafka_metrics"

    def to_printed_hogql(self):
        return "metrics_kafka_metrics"
