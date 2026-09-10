from temporalio import activity, workflow
from temporalio.common import MetricCounter, MetricHistogramFloat

from posthog.dataclasses import frozen

# custom latency histogram buckets,
# since we lose some important granularity with default max at 60s
DATA_MODELING_LATENCY_HISTOGRAM_METRICS = (
    "temporal_activity_execution_latency",
    "temporal_activity_schedule_to_start_latency",
    "temporal_workflow_task_execution_latency",
    "temporal_workflow_task_schedule_to_start_latency",
    "temporal_workflow_endtoend_latency",
)
DATA_MODELING_LATENCY_HISTOGRAM_BUCKETS = [
    1.0,  # 1ms
    10.0,  # 10ms
    50.0,  # 50ms
    100.0,  # 100ms
    500.0,  # 500ms
    1_000.0,  # 1s
    5_000.0,  # 5s
    30_000.0,  # 30s
    60_000.0,  # 1m (old ceiling)
    120_000.0,  # 2m
    300_000.0,  # 5m
    900_000.0,  # 15m
    1_800_000.0,  # 30m
    3_600_000.0,  # 1h (run_dag_activity start_to_close_timeout)
]


def get_data_modeling_finished_metric(status: str) -> MetricCounter:
    return (
        workflow.metric_meter()
        .with_additional_attributes({"status": status})
        .create_counter(
            "data_modeling_finished", "Number of data modeling runs finished, for any reason (including failure)."
        )
    )


def get_node_suspended_metric(engine: str) -> MetricCounter:
    return (
        activity.metric_meter()
        .with_additional_attributes({"engine": engine})
        .create_counter(
            "data_modeling_node_suspended",
            "Number of nodes suspended after repeated materialization failures, by engine.",
        )
    )


@frozen
class _DualMetricCounters:
    managed_warehouse: MetricCounter
    legacy_duckgres: MetricCounter

    def add(self, value: int) -> None:
        self.managed_warehouse.add(value)
        self.legacy_duckgres.add(value)


@frozen
class _DualMetricHistograms:
    managed_warehouse: MetricHistogramFloat
    legacy_duckgres: MetricHistogramFloat

    def record(self, value: float) -> None:
        self.managed_warehouse.record(value)
        self.legacy_duckgres.record(value)


def get_managed_warehouse_shadow_finished_metrics(status: str) -> _DualMetricCounters:
    meter = workflow.metric_meter().with_additional_attributes({"status": status})
    description = "Number of managed warehouse shadow materialization activities finished, by status."
    return _DualMetricCounters(
        managed_warehouse=meter.create_counter("managed_warehouse_shadow_materialization_finished", description),
        legacy_duckgres=meter.create_counter("duckgres_shadow_materialization_finished", description),
    )


def get_managed_warehouse_shadow_row_count_match_metrics(matched: bool) -> _DualMetricCounters:
    meter = workflow.metric_meter().with_additional_attributes({"matched": str(matched).lower()})
    description = "Row count comparison between ClickHouse and managed warehouse shadow materializations."
    return _DualMetricCounters(
        managed_warehouse=meter.create_counter("managed_warehouse_shadow_row_count_comparison", description),
        legacy_duckgres=meter.create_counter("duckgres_shadow_row_count_comparison", description),
    )


def get_managed_warehouse_shadow_duration_metrics() -> _DualMetricHistograms:
    meter = workflow.metric_meter()
    description = "Duration of managed warehouse shadow materialization in seconds."
    return _DualMetricHistograms(
        managed_warehouse=meter.create_histogram_float(
            "managed_warehouse_shadow_materialization_duration_seconds", description, "s"
        ),
        legacy_duckgres=meter.create_histogram_float(
            "duckgres_shadow_materialization_duration_seconds", description, "s"
        ),
    )


def get_managed_warehouse_shadow_rows_materialized_metrics() -> _DualMetricHistograms:
    meter = workflow.metric_meter()
    description = "Number of rows materialized per managed warehouse shadow materialization."
    return _DualMetricHistograms(
        managed_warehouse=meter.create_histogram_float("managed_warehouse_shadow_rows_materialized", description),
        legacy_duckgres=meter.create_histogram_float("duckgres_shadow_rows_materialized", description),
    )


def get_managed_warehouse_shadow_storage_mib_metrics() -> _DualMetricHistograms:
    meter = workflow.metric_meter()
    description = "Total DuckLake storage size (MiB) after a managed warehouse shadow materialization."
    return _DualMetricHistograms(
        managed_warehouse=meter.create_histogram_float("managed_warehouse_shadow_storage_mib", description, "MiB"),
        legacy_duckgres=meter.create_histogram_float("duckgres_shadow_storage_mib", description, "MiB"),
    )


def get_managed_warehouse_shadow_storage_delta_mib_metrics() -> _DualMetricHistograms:
    meter = workflow.metric_meter()
    description = "Change in DuckLake storage size (MiB) after a managed warehouse shadow materialization."
    return _DualMetricHistograms(
        managed_warehouse=meter.create_histogram_float(
            "managed_warehouse_shadow_storage_delta_mib", description, "MiB"
        ),
        legacy_duckgres=meter.create_histogram_float("duckgres_shadow_storage_delta_mib", description, "MiB"),
    )


def get_clickhouse_materialization_duration_metric() -> MetricHistogramFloat:
    return workflow.metric_meter().create_histogram_float(
        "clickhouse_materialization_duration_seconds",
        "Duration of ClickHouse materialization in seconds.",
        "s",
    )


# DAG-level metrics (v2 ExecuteDAGWorkflow)


def get_dag_finished_metric(status: str) -> MetricCounter:
    return (
        workflow.metric_meter()
        .with_additional_attributes({"status": status})
        .create_counter(
            "data_modeling_dag_finished",
            "Number of DAG executions finished. Status is completed, partial_failure, skipped, or failed.",
        )
    )


def get_dag_duration_metric() -> MetricHistogramFloat:
    return workflow.metric_meter().create_histogram_float(
        "data_modeling_dag_duration_seconds",
        "Total wall-clock duration of a DAG execution.",
        "s",
    )


def get_dag_node_count_metric(outcome: str) -> MetricHistogramFloat:
    return (
        workflow.metric_meter()
        .with_additional_attributes({"outcome": outcome})
        .create_histogram_float(
            "data_modeling_dag_node_count",
            "Number of nodes per outcome (successful, failed, skipped) in a DAG execution.",
        )
    )


# Node-level metrics (v2 MaterializeViewWorkflow)


def get_node_finished_metric(status: str) -> MetricCounter:
    return (
        workflow.metric_meter()
        .with_additional_attributes({"status": status})
        .create_counter(
            "data_modeling_node_finished",
            "Number of node materializations finished. Status is completed, failed, or cancelled.",
        )
    )


def get_node_duration_metric() -> MetricHistogramFloat:
    return workflow.metric_meter().create_histogram_float(
        "data_modeling_node_duration_seconds",
        "Wall-clock duration of a single node materialization.",
        "s",
    )


def get_node_rows_materialized_metric() -> MetricHistogramFloat:
    return workflow.metric_meter().create_histogram_float(
        "data_modeling_node_rows_materialized",
        "Number of rows materialized per node.",
    )


def get_node_storage_delta_mib_metric() -> MetricHistogramFloat:
    return workflow.metric_meter().create_histogram_float(
        "data_modeling_node_storage_delta_mib",
        "Change in S3 storage size (MiB) after a node materialization.",
        "MiB",
    )


def get_node_total_storage_mib_metric() -> MetricHistogramFloat:
    return workflow.metric_meter().create_histogram_float(
        "data_modeling_node_total_storage_mib",
        "Total S3 storage size (MiB) of the materialized table after a node materialization.",
        "MiB",
    )
