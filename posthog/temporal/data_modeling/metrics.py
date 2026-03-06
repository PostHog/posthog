from temporalio import workflow
from temporalio.common import MetricCounter, MetricHistogramFloat


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


def get_clickhouse_materialization_duration_metric() -> MetricHistogramFloat:
    return workflow.metric_meter().create_histogram_float(
        "clickhouse_materialization_duration_seconds",
        "Duration of ClickHouse materialization in seconds.",
        "s",
    )
