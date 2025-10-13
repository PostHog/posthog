from temporalio import activity
from temporalio.common import MetricCounter


def get_block_loaded_counter() -> MetricCounter:
    return activity.metric_meter().create_counter("recording_block_loaded", "Number of recording blocks loaded.")


def get_block_deleted_counter() -> MetricCounter:
    return activity.metric_meter().create_counter("recording_block_deleted", "Number of recording blocks deleted.")


def get_block_deleted_error_counter() -> MetricCounter:
    return activity.metric_meter().create_counter(
        "recording_block_deleted_error", "Number of recording block errors encountered."
    )
