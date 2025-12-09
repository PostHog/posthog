from temporalio import workflow
from temporalio.common import MetricCounter


def get_data_import_finished_metric(source_type: str | None, status: str) -> MetricCounter:
    source_type = source_type or "unknown"
    return (
        workflow.metric_meter()
        .with_additional_attributes({"source_type": source_type, "status": status})
        .create_counter("data_import_finished", "Number of data imports finished, for any reason (including failure).")
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
