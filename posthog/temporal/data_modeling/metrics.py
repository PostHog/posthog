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
