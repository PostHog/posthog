import re

from temporalio import activity, workflow
from temporalio.common import MetricCounter, MetricHistogramFloat

from products.data_modeling.backend.temporal.activities.utils import is_externally_aborted
from products.managed_warehouse.backend.facade.contracts import TRINO_INSTANCE_REPLACED_ERROR_PREFIX

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

# The SDK defaults (50s to 10,000s) leave both fast ClickHouse nodes and long Trino runs unreadable.
DATA_MODELING_DURATION_HISTOGRAM_METRICS = (
    "data_modeling_node_duration_seconds",
    "data_modeling_dag_duration_seconds",
)
DATA_MODELING_DURATION_HISTOGRAM_BUCKETS = [
    5.0,
    15.0,
    30.0,
    60.0,
    120.0,
    300.0,
    600.0,
    1_200.0,
    1_800.0,
    3_600.0,
    7_200.0,
    14_400.0,
    21_600.0,
    43_200.0,
    82_800.0,  # TRINO_SHADOW_RUN_TIMEOUT
]

AD_HOC_TIER = "ad_hoc"
UNKNOWN_RUN_MODE = "unknown"

# Tier schedule runs are `execute-dag-{dag_id}:{seconds}[:{anchor}]-{timestamp}`, and their Trino
# shadows are `execute-dag-trino-{dag_id}:{seconds}[:{anchor}]`.
_TIER_WORKFLOW_ID = re.compile(r"^execute-dag-(?:trino-)?[0-9a-f-]{36}:(\d+)")


NO_ERROR_LABEL = "none"
OTHER_ERROR_CODE = "other"
DEADLINE_EXCEEDED_ERROR_CODE = "DEADLINE_EXCEEDED"
TRINO_DEADLINE_ERROR_PREFIXES = (
    "Trino model execution exceeded its ",
    "Trino model execution was canceled or exceeded its deadline",
)
_TRINO_COMPILER_CODE = re.compile(r"\[(TRINO_[A-Z0-9_]+)\]")
_TRINO_ERROR_NAME = re.compile(r"Trino\w*Error\(type=\w+, name=(\w+),")
_HTTP_ERROR_STATUS = re.compile(r"error (\d{3}):")


def tier_label(dag_workflow_id: str | None) -> str:
    """The cadence tier in seconds of the DAG run with this workflow id, or `ad_hoc` for any other run."""
    match = _TIER_WORKFLOW_ID.match(dag_workflow_id or "")
    return match.group(1) if match else AD_HOC_TIER


def get_node_suspended_metric(engine: str) -> MetricCounter:
    return (
        activity.metric_meter()
        .with_additional_attributes({"engine": engine})
        .create_counter(
            "data_modeling_node_suspended",
            "Number of nodes suspended after repeated materialization failures, by engine.",
        )
    )


def get_managed_warehouse_trino_compile_failure_metric(error_code: str) -> MetricCounter:
    return (
        activity.metric_meter()
        .with_additional_attributes({"error_code": error_code})
        .create_counter(
            "managed_warehouse_shadow_trino_compile_failure",
            "Number of managed warehouse shadow views that Trino compilation rejected, by error code.",
        )
    )


def get_managed_warehouse_trino_missing_object_metric(error_name: str) -> MetricCounter:
    return (
        activity.metric_meter()
        .with_additional_attributes({"error_name": error_name})
        .create_counter(
            "managed_warehouse_shadow_trino_missing_object",
            "Number of managed warehouse shadow builds that failed because Trino could not resolve a catalog, schema, table or column, by error name.",
        )
    )


# DAG-level metrics (v2 ExecuteDAGWorkflow)


def get_dag_finished_metric(status: str, engine: str, *, tier: str) -> MetricCounter:
    return (
        workflow.metric_meter()
        .with_additional_attributes({"status": status, "engine": engine, "tier_seconds": tier})
        .create_counter(
            "data_modeling_dag_finished",
            "Number of DAG executions finished. Status is completed, partial_failure, skipped, or failed.",
        )
    )


def get_dag_duration_metric(engine: str, *, tier: str) -> MetricHistogramFloat:
    return (
        workflow.metric_meter()
        .with_additional_attributes({"engine": engine, "tier_seconds": tier})
        .create_histogram_float(
            "data_modeling_dag_duration_seconds",
            "Total wall-clock duration of a DAG execution.",
            "s",
        )
    )


def get_dag_node_count_metric(outcome: str, engine: str) -> MetricHistogramFloat:
    return (
        workflow.metric_meter()
        .with_additional_attributes({"outcome": outcome, "engine": engine})
        .create_histogram_float(
            "data_modeling_dag_node_count",
            "Number of nodes per outcome (successful, failed, skipped) in a DAG execution.",
        )
    )


# Node-level metrics (v2 MaterializeViewWorkflow)


def get_trino_shadow_start_metric(outcome: str) -> MetricCounter:
    return (
        workflow.metric_meter()
        .with_additional_attributes({"outcome": outcome})
        .create_counter(
            "data_modeling_trino_shadow_start",
            "Trino shadow run start attempts. Outcome is started, skipped_still_running, or error.",
        )
    )


def get_node_finished_metric(
    status: str,
    engine: str,
    *,
    tier: str,
    run_mode: str,
    error_class: str = NO_ERROR_LABEL,
    error_code: str = NO_ERROR_LABEL,
) -> MetricCounter:
    return (
        workflow.metric_meter()
        .with_additional_attributes(
            {
                "status": status,
                "engine": engine,
                "tier_seconds": tier,
                "run_mode": run_mode,
                "error_class": error_class,
                "error_code": error_code,
            }
        )
        .create_counter(
            "data_modeling_node_finished",
            "Number of node materializations finished. Status is completed, failed, cancelled, or quality_blocked. "
            "A failure's error_class is infra when it does not count toward suspension, otherwise other. "
            "A managed warehouse failure's error_code is the Trino compiler code, the Trino error name, "
            "HTTP_<status>, DEADLINE_EXCEEDED, or other.",
        )
    )


def error_class(error: str) -> str:
    return "infra" if is_externally_aborted(error) else "other"


def error_code(error: str) -> str:
    named = _TRINO_COMPILER_CODE.match(error) or _TRINO_ERROR_NAME.match(error)
    if named:
        return named.group(1)
    http_status = _HTTP_ERROR_STATUS.match(error)
    if http_status:
        return f"HTTP_{http_status.group(1)}"
    if error.startswith(TRINO_DEADLINE_ERROR_PREFIXES):
        return DEADLINE_EXCEEDED_ERROR_CODE
    if error.startswith(TRINO_INSTANCE_REPLACED_ERROR_PREFIX):
        return "ADMINISTRATIVELY_KILLED"
    return OTHER_ERROR_CODE


def get_node_duration_metric(engine: str, *, run_mode: str) -> MetricHistogramFloat:
    return (
        workflow.metric_meter()
        .with_additional_attributes({"engine": engine, "run_mode": run_mode})
        .create_histogram_float(
            "data_modeling_node_duration_seconds",
            "Wall-clock duration of a single node materialization.",
            "s",
        )
    )


def get_node_rows_materialized_metric(engine: str) -> MetricHistogramFloat:
    return (
        workflow.metric_meter()
        .with_additional_attributes({"engine": engine})
        .create_histogram_float(
            "data_modeling_node_rows_materialized",
            "Number of rows materialized per node.",
        )
    )


def get_node_storage_delta_mib_metric(engine: str) -> MetricHistogramFloat:
    return (
        workflow.metric_meter()
        .with_additional_attributes({"engine": engine})
        .create_histogram_float(
            "data_modeling_node_storage_delta_mib",
            "Change in storage size (MiB) after a node materialization.",
            "MiB",
        )
    )


def get_node_total_storage_mib_metric(engine: str) -> MetricHistogramFloat:
    return (
        workflow.metric_meter()
        .with_additional_attributes({"engine": engine})
        .create_histogram_float(
            "data_modeling_node_total_storage_mib",
            "Total storage size (MiB) of the materialized table after a node materialization.",
            "MiB",
        )
    )
