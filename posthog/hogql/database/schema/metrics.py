from posthog.hogql.ast import SelectQuery
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.lazy_join_tags import METRICS_TO_METRIC_SERIES
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DANGEROUS_NoTeamIdCheckTable,
    DateTimeDatabaseField,
    FieldOrTable,
    FloatDatabaseField,
    IntegerDatabaseField,
    LazyJoin,
    LazyJoinToAdd,
    MapStringDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
)
from posthog.hogql.errors import ResolutionError

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
        # Lazy join that adds the series labels (attributes, resource_attributes) by joining
        # metric_series on series_fingerprint. Access labels via `series.attributes.*`.
        "series": LazyJoin(
            from_field=["series_fingerprint"],
            join_table="posthog.metric_series",
            resolver=METRICS_TO_METRIC_SERIES,
        ),
    }

    def to_printed_clickhouse(self, context):
        return "metrics_distributed"

    def to_printed_hogql(self):
        return "metrics"


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
            name="last_seen", nullable=False, description="Most recent sample timestamp seen for this series."
        ),
        "original_expiry_timestamp": DateTimeDatabaseField(
            name="original_expiry_timestamp", nullable=False, description="When the series leaves retention."
        ),
    }

    def to_printed_clickhouse(self, context):
        return "metric_series_distributed"

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
        "service_name": StringDatabaseField(
            name="service_name", nullable=False, description="Service the attribute counts are scoped to."
        ),
        "original_expiry_time_bucket": DateTimeDatabaseField(
            name="original_expiry_time_bucket", nullable=False, description="When the bucket leaves retention."
        ),
    }

    def to_printed_clickhouse(self, context):
        return "metric_attributes_distributed"

    def to_printed_hogql(self):
        return "metric_attributes"


def join_metrics_with_metric_series_table(
    join_to_add: LazyJoinToAdd,
    context: HogQLContext,
    node: SelectQuery,
):
    from posthog.hogql import ast

    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from metric_series")

    # metric_series is a ReplacingMergeTree keyed on (team_id, metric_name, series_fingerprint) with
    # duplicate rows per series (replaced by last_seen). Deduplicate to one row per fingerprint so the
    # join can't fan out the metrics rows, then join on the fingerprint. team_id is added by HogQL's
    # automatic team scoping on the subquery.
    inner_select = ast.SelectQuery(
        select=[
            ast.Alias(alias="series_fingerprint", expr=ast.Field(chain=["series_fingerprint"])),
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=["posthog", "metric_series"])),
        group_by=[ast.Field(chain=["series_fingerprint"])],
    )
    for field_name, field_chain in join_to_add.fields_accessed.items():
        # series_fingerprint is already selected as the join key.
        if field_name == "series_fingerprint":
            continue
        inner_select.select.append(
            ast.Alias(
                alias=field_name,
                expr=ast.Call(name="any", args=[ast.Field(chain=list(field_chain))]),
            )
        )

    join_expr = ast.JoinExpr(table=inner_select)
    join_expr.join_type = "LEFT JOIN"
    join_expr.alias = join_to_add.to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=[join_to_add.from_table, "series_fingerprint"]),
            right=ast.Field(chain=[join_to_add.to_table, "series_fingerprint"]),
        ),
        constraint_type="ON",
    )
    return join_expr


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
