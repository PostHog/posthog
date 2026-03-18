from temporalio import workflow
from temporalio.common import MetricCounter


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


def get_ducklake_copy_data_imports_finished_metric(status: str) -> MetricCounter:
    return (
        workflow.metric_meter()
        .with_additional_attributes({"status": status})
        .create_counter(
            "ducklake_copy_data_imports_finished",
            "Number of DuckLake data imports copy workflows finished, including failures.",
        )
    )


def get_ducklake_copy_data_imports_verification_metric(check_name: str, status: str) -> MetricCounter:
    return (
        workflow.metric_meter()
        .with_additional_attributes({"check": check_name, "status": status})
        .create_counter(
            "ducklake_copy_data_imports_verification",
            "Number of DuckLake data imports verification checks completed.",
        )
    )
