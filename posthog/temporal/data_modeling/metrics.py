from temporalio import workflow
from temporalio.common import MetricCounter, MetricHistogramFloat

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


def get_duckgres_shadow_finished_metric(status: str) -> MetricCounter:
    return (
        workflow.metric_meter()
        .with_additional_attributes({"status": status})
        .create_counter(
            "duckgres_shadow_materialization_finished",
            "Number of duckgres shadow materialization activities finished, by status.",
        )
    )


def get_duckgres_shadow_row_count_match_metric(matched: bool) -> MetricCounter:
    return (
        workflow.metric_meter()
        .with_additional_attributes({"matched": str(matched).lower()})
        .create_counter(
            "duckgres_shadow_row_count_comparison",
            "Row count comparison between ClickHouse and duckgres shadow materializations.",
        )
    )


def get_duckgres_shadow_duration_metric() -> MetricHistogramFloat:
    return workflow.metric_meter().create_histogram_float(
        "duckgres_shadow_materialization_duration_seconds",
        "Duration of duckgres shadow materialization in seconds.",
        "s",
    )


def get_duckgres_shadow_rows_materialized_metric() -> MetricHistogramFloat:
    return workflow.metric_meter().create_histogram_float(
        "duckgres_shadow_rows_materialized",
        "Number of rows materialized per duckgres shadow materialization.",
    )


def get_duckgres_shadow_storage_mib_metric() -> MetricHistogramFloat:
    return workflow.metric_meter().create_histogram_float(
        "duckgres_shadow_storage_mib",
        "Total DuckLake storage size (MiB) of the materialized table after a duckgres shadow materialization.",
        "MiB",
    )


def get_duckgres_shadow_storage_delta_mib_metric() -> MetricHistogramFloat:
    return workflow.metric_meter().create_histogram_float(
        "duckgres_shadow_storage_delta_mib",
        "Change in DuckLake storage size (MiB) after a duckgres shadow materialization.",
        "MiB",
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
