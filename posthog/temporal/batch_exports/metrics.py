import contextlib
import datetime as dt
import time

from temporalio import activity, workflow
from temporalio.common import MetricCounter

from posthog.temporal.common.logger import get_internal_logger


def get_rows_exported_metric() -> MetricCounter:
    return activity.metric_meter().create_counter("batch_export_rows_exported", "Number of rows exported.")


def get_bytes_exported_metric() -> MetricCounter:
    return activity.metric_meter().create_counter("batch_export_bytes_exported", "Number of bytes exported.")


def get_export_started_metric() -> MetricCounter:
    return workflow.metric_meter().create_counter("batch_export_started", "Number of batch exports started.")


def get_export_finished_metric(status: str) -> MetricCounter:
    return (
        workflow.metric_meter()
        .with_additional_attributes({"status": status})
        .create_counter(
            "batch_export_finished", "Number of batch exports finished, for any reason (including failure)."
        )
    )


@contextlib.contextmanager
def execution_time_tracker(
    human_readable_name: str,
    /,
    description: str | None = None,
    additional_attributes: dict[str, str | int | float | bool] | None = None,
    log: bool = True,
):
    """Track execution time of sections of a batch export within context.

    Arguments:
        human_readable_name: The name of the metric. The human readable part
            indicates this should be with whole words separated with spaces. The
            meter name will be derived by converting the name to snake_case.
        description: Description to use for the metric.
        additional_attributes: Mapping of any attributes to add to meter. This
            function already adds common attributes like 'workflow_id' or
            'activity_type'. Moreover, a 'status' will be added to indicate if
            an exception was raised within the block ('Failed') or not
            ('Completed').
        log: Whether to additionally log the execution time.
    """
    start_counter = time.perf_counter()
    name = human_readable_name.replace(" ", "_").lower()
    exception = None

    try:
        yield
    except Exception as exc:
        exception = exc
    finally:
        end_counter = time.perf_counter()
        delta_milli_seconds = int((end_counter - start_counter) * 1000)
        delta = dt.timedelta(milliseconds=delta_milli_seconds)

        meter = activity.metric_meter()
        info = activity.info()

        attributes = {
            "status": "Failed" if exception else "Completed",
            "error": str(exception) if exception else "",
            "attempt": info.attempt,
            "namespace": info.workflow_namespace,
            "workflow_id": info.workflow_id,
            "workflow_run_id": info.workflow_run_id,
            "workflow_type": info.workflow_type,
            "activity_id": info.activity_id,
            "activity_type": info.activity_type,
        }

        if additional_attributes:
            attributes = {**attributes, **additional_attributes}
        meter = meter.with_additional_attributes(attributes)

        hist = meter.create_histogram_timedelta(name=name, description=description, unit="ms")
        hist.record(value=delta)

        if log:
            log_execution_time(human_readable_name, delta, exception)


def log_execution_time(human_readable_name: str, delta: dt.timedelta, exception: Exception | None = None):
    logger = get_internal_logger()

    if exception:
        logger.info("Execution of %s FAILED in %.4fs", human_readable_name, delta.total_seconds())
    else:
        logger.info("Execution of %s COMPLETED in %.4fs", human_readable_name, delta.total_seconds())
