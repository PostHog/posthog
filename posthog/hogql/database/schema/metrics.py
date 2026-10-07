from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DANGEROUS_NoTeamIdCheckTable,
    DateTimeArrayDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    FloatArrayDatabaseField,
    FloatDatabaseField,
    IntegerArrayDatabaseField,
    IntegerDatabaseField,
    MapStringDatabaseField,
    StringArrayDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
    UnknownDatabaseField,
)

from posthog.clickhouse.workload import Workload

# 50GB - limit for user-provided HogQL queries on metrics tables to prevent expensive full scans
HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES = 50_000_000_000


class MetricsTable(Table):
    description: str = "OpenTelemetry metric data points (gauges, sums, histograms), one row per data point. Labels are not on the row: join `metric_series` on `series_fingerprint` for `attributes` and `resource_attributes`."
    workload: Workload | None = Workload.LOGS  # reuse LOGS workload for now

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "series_fingerprint": IntegerDatabaseField(
            name="series_fingerprint",
            nullable=False,
            description="Hash of the series' label set, assigned at ingest; join key to `metric_series`.",
        ),
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
        "original_expiry_timestamp": DateTimeDatabaseField(
            name="original_expiry_timestamp", nullable=False, description="When the data point leaves retention."
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
        "has_labels": BooleanDatabaseField(
            name="has_labels",
            nullable=False,
            description="True when the ingested record carried the series labels; only such records write `metric_series` and `metric_attributes` rows.",
        ),
    }

    def to_printed_clickhouse(self, context):
        return "metrics4_view"

    def to_printed_hogql(self):
        return "metrics"


class MetricSamplesTable(Table):
    description: str = "OpenTelemetry metric data points grouped by series and UTC hour. Each row holds the points of one series-hour in parallel arrays, so the same array index identifies one point. Use `ARRAY JOIN` to read one row per point. One series-hour can have more than one row until ClickHouse merges them. Join `metric_series` on `series_fingerprint` for labels."
    workload: Workload | None = Workload.LOGS

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "metric_name": StringDatabaseField(name="metric_name", nullable=False, description="Name of the metric."),
        "time_bucket": DateTimeDatabaseField(
            name="time_bucket", nullable=False, description="Start of the UTC hour of all points in the row."
        ),
        "series_fingerprint": IntegerDatabaseField(
            name="series_fingerprint",
            nullable=False,
            description="Hash of the series' label set, assigned at ingest; join key to `metric_series`.",
        ),
        "resource_fingerprint": IntegerDatabaseField(
            name="resource_fingerprint",
            nullable=False,
            description="Hash of the resource attributes, used to group resources.",
        ),
        "service_name": StringDatabaseField(
            name="service_name", nullable=False, description="Name of the service that emitted the metric."
        ),
        "metric_type": StringDatabaseField(
            name="metric_type",
            nullable=False,
            description="OpenTelemetry metric type, e.g. 'gauge', 'sum', 'histogram'.",
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
        "has_labels": BooleanDatabaseField(
            name="has_labels",
            nullable=False,
            description="True when an ingested record of the row carried the series labels.",
        ),
        "instrumentation_scope": StringDatabaseField(
            name="instrumentation_scope",
            nullable=False,
            description="Instrumentation scope (library/module) that emitted the metric.",
        ),
        "histogram_bounds": FloatArrayDatabaseField(
            name="histogram_bounds", nullable=False, description="Histogram bucket boundaries of the series."
        ),
        "timestamp_min": DateTimeDatabaseField(
            name="timestamp_min", nullable=False, description="Earliest point timestamp in the row."
        ),
        "timestamp_max": DateTimeDatabaseField(
            name="timestamp_max", nullable=False, description="Latest point timestamp in the row."
        ),
        "timestamp_arr": DateTimeArrayDatabaseField(
            name="timestamp_arr", nullable=False, description="When each data point was recorded."
        ),
        "observed_timestamp_arr": DateTimeArrayDatabaseField(
            name="observed_timestamp_arr",
            nullable=False,
            description="When the collector observed each data point.",
        ),
        "value_arr": FloatArrayDatabaseField(
            name="value_arr", nullable=False, description="Numeric value of each data point (for gauge/sum metrics)."
        ),
        "count_arr": IntegerArrayDatabaseField(
            name="count_arr",
            nullable=False,
            description="Total count of observations of each data point (for histogram metrics).",
        ),
        "histogram_counts_arr": UnknownDatabaseField(
            name="histogram_counts_arr",
            nullable=False,
            description="Per-bucket counts of each data point, aligned with `histogram_bounds`.",
        ),
        "trace_id_arr": StringArrayDatabaseField(
            name="trace_id_arr", nullable=False, description="Trace of each metric exemplar, if any."
        ),
        "span_id_arr": StringArrayDatabaseField(
            name="span_id_arr", nullable=False, description="Span of each metric exemplar, if any."
        ),
        "trace_flags_arr": IntegerArrayDatabaseField(
            name="trace_flags_arr", nullable=False, description="Trace flags of each metric exemplar."
        ),
    }

    def to_printed_clickhouse(self, context):
        return "metrics4_samples"

    def to_printed_hogql(self):
        return "metric_samples"


class MetricNamesTable(Table):
    description: str = "One row per metric name, service and UTC hour with labeled data points. Use it to find the metric names of a time range."
    workload: Workload | None = Workload.LOGS

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "metric_name": StringDatabaseField(name="metric_name", nullable=False, description="Name of the metric."),
        "time_bucket": DateTimeDatabaseField(
            name="time_bucket", nullable=False, description="UTC hour in which the metric had data points."
        ),
        "original_expiry_time_bucket": DateTimeDatabaseField(
            name="original_expiry_time_bucket", nullable=False, description="Hour in which the row leaves retention."
        ),
        "original_expiry_timestamp": DateTimeDatabaseField(
            name="original_expiry_timestamp", nullable=False, description="When the row leaves retention."
        ),
        "service_name": StringDatabaseField(
            name="service_name", nullable=False, description="Name of the service that emitted the metric."
        ),
    }

    def to_printed_clickhouse(self, context):
        return "metrics4_names"

    def to_printed_hogql(self):
        return "metric_names"


class MetricSeriesTable(Table):
    description: str = "One row per unique metric series (metric + label set), keyed by `series_fingerprint`. Labels are stored here once and joined to `metrics` at query time."
    workload: Workload | None = Workload.LOGS

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "metric_name": StringDatabaseField(name="metric_name", nullable=False),
        "series_fingerprint": IntegerDatabaseField(
            name="series_fingerprint",
            nullable=False,
            description="Hash of the label set; join key from `metrics`.",
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
        "instrumentation_scope": StringDatabaseField(name="instrumentation_scope", nullable=False),
        "resource_attributes": MapStringDatabaseField(name="resource_attributes", nullable=False),
        "resource_fingerprint": IntegerDatabaseField(
            name="resource_fingerprint",
            nullable=False,
            description="Hash of `resource_attributes`; matches `metrics.resource_fingerprint`.",
        ),
        "attributes": MapStringDatabaseField(name="attributes", nullable=False),
        "last_seen": DateTimeDatabaseField(
            name="timestamp", nullable=False, description="Most recent sample timestamp seen for this series."
        ),
        "time_bucket": DateTimeDatabaseField(
            name="time_bucket", nullable=False, description="Start of the UTC hour that contains `last_seen`."
        ),
        "original_expiry_timestamp": DateTimeDatabaseField(
            name="original_expiry_timestamp", nullable=False, description="When the series leaves retention."
        ),
    }

    def to_printed_clickhouse(self, context):
        return "metrics4_series"

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
        "metric_name": StringDatabaseField(name="metric_name", nullable=False),
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
        "service_name": StringDatabaseField(
            name="service_name", nullable=False, description="Service the attribute counts are scoped to."
        ),
        "original_expiry_time_bucket": DateTimeDatabaseField(
            name="original_expiry_time_bucket", nullable=False, description="When the bucket leaves retention."
        ),
    }

    def to_printed_clickhouse(self, context):
        return "metrics4_attributes"

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
