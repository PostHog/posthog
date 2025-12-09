from temporalio import workflow
from temporalio.common import MetricCounter


def get_data_modeling_finished_metric(status: str) -> MetricCounter:
    return (
        workflow.metric_meter()
        .with_additional_attributes({"status": status})
        .create_counter(
            "data_modeling_finished", "Number of data modeling runs finished, for any reason (including failure)."
        )
    )


def get_ducklake_copy_data_modeling_finished_metric(status: str) -> MetricCounter:
    return (
        workflow.metric_meter()
        .with_additional_attributes({"status": status})
        .create_counter(
            "ducklake_copy_data_modeling_finished",
            "Number of DuckLake data modeling copy workflows finished, including failures.",
        )
    )


def get_ducklake_copy_data_modeling_verification_metric(check: str, status: str) -> MetricCounter:
    return (
        workflow.metric_meter()
        .with_additional_attributes({"check": check, "status": status})
        .create_counter(
            "ducklake_copy_data_modeling_verification",
            "Number of DuckLake data modeling verification checks executed grouped by status.",
        )
    )
