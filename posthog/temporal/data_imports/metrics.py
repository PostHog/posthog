from temporalio import workflow
from temporalio.common import MetricCounter


def get_data_import_finished_metric(source_type: str | None, status: str) -> MetricCounter:
    source_type = source_type or "unknown"
    return (
        workflow.metric_meter()
        .with_additional_attributes({"source_type": source_type, "status": status})
        .create_counter("data_import_finished", "Number of data imports finished, for any reason (including failure).")
    )
