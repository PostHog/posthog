import datetime as dt
import time
import typing

import structlog
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


Attributes = dict[str, str | int | float | bool]


class ExecutionTimeRecorder:
    def __init__(
        self,
        histogram_name: str,
        /,
        description: str | None = None,
        histogram_attributes: Attributes | None = None,
        log: bool = True,
        log_message: str = "Finished %(name)s with status '%(status)s' in %(duration_seconds)ds",
        log_name: str | None = None,
        log_attributes: Attributes | None = None,
    ) -> None:
        """Context manager to record execution time to a histogram metric.

        This can be used from within a workflow or an activity.

        Attributes:
            histogram_name: A name for the histogram metric.
            description: Description to use for the metric.
            histogram_attributes: Mapping of any attributes to add to meter.
                This tracker already adds common attributes like 'workflow_id'
                or 'activity_type'. Moreover, a 'status' will be added to
                indicate if an exception was raised within the block ('FAILED')
                or not ('COMPLETED').
            log: Whether to additionally log the execution time.
            log_message: Use a custom log message.
            log_name: Provide an alternative name for the log line instead of
                using the histogram name.
            log_attributes: Mapping of additional attributes available to pass
                to the logger.
        """

        self.histogram_name = histogram_name
        self.description = description
        self.histogram_attributes = histogram_attributes
        self.log = log
        self.log_message = log_message
        self.log_name = log_name
        self.log_attributes = log_attributes
        self.bytes_processed: None | int = None

        self._start_counter: float | None = None

    def __enter__(self) -> typing.Self:
        """Start the counter and return."""
        self._start_counter = time.perf_counter()
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback) -> None:
        """Record execution time on exiting.

        No exceptions from within the context are handled in this method.
        Exception information is used to set status.
        """
        if not self._start_counter:
            raise RuntimeError("Start counter not initialized, did you call `__enter__`?")

        start_counter = self._start_counter
        end_counter = time.perf_counter()
        delta_milli_seconds = int((end_counter - start_counter) * 1000)
        delta = dt.timedelta(milliseconds=delta_milli_seconds)

        attributes = get_attributes(self.histogram_attributes)
        if exc_value is not None:
            attributes["status"] = "FAILED"
            attributes["exception"] = str(exc_value)
        else:
            attributes["status"] = "COMPLETED"
            attributes["exception"] = ""

        meter = get_metric_meter(attributes)
        hist = meter.create_histogram_timedelta(name=self.histogram_name, description=self.description, unit="ms")
        try:
            hist.record(value=delta)
        except Exception:
            logger = get_internal_logger()
            logger.exception("Failed to record execution time to histogram '%s'", self.histogram_name)

        if self.log:
            log_execution_time(
                self.log_message,
                name=self.log_name or self.histogram_name,
                delta=delta,
                status="FAILED" if exc_value else "COMPLETED",
                bytes_processed=self.bytes_processed,
                extra_arguments=self.log_attributes,
            )

        self.reset()

    def add_bytes_processed(self, bytes_processed: int) -> int:
        """Add to bytes processed, returning the total so far."""
        if self.bytes_processed is None:
            self.bytes_processed = bytes_processed
        else:
            self.bytes_processed += bytes_processed

        return self.bytes_processed

    def reset(self):
        """Reset counter and bytes processed."""
        self._start_counter = None
        self.bytes_processed = None


def get_metric_meter(additional_attributes: Attributes | None = None):
    """Return a meter depending on in which context we are."""
    if activity.in_activity():
        meter = activity.metric_meter()
    else:
        try:
            meter = workflow.metric_meter()
        except Exception:
            raise RuntimeError("Not within workflow or activity context")

    if additional_attributes:
        meter = meter.with_additional_attributes(additional_attributes)

    return meter


def get_attributes(additional_attributes: Attributes | None = None) -> Attributes:
    """Return attributes depending on in which context we are."""
    if activity.in_activity():
        attributes = get_activity_attributes()
    else:
        try:
            attributes = get_workflow_attributes()
        except Exception:
            attributes = {}

    if additional_attributes:
        attributes = {**attributes, **additional_attributes}

    return attributes


def get_activity_attributes() -> Attributes:
    """Return basic Temporal.io activity attributes."""
    info = activity.info()

    return {
        "workflow_namespace": info.workflow_namespace,
        "workflow_type": info.workflow_type,
        "activity_type": info.activity_type,
    }


def get_workflow_attributes() -> Attributes:
    """Return basic Temporal.io workflow attributes."""
    info = workflow.info()

    return {
        "workflow_namespace": info.namespace,
        "workflow_type": info.workflow_type,
    }


def log_execution_time(
    log_message: str,
    name: str,
    delta: dt.timedelta,
    status: str,
    bytes_processed: None | int = None,
    extra_arguments: Attributes | None = None,
):
    """Log execution time."""
    logger = get_internal_logger()

    duration_seconds = delta.total_seconds()

    if bytes_processed is not None:
        mb_processed = bytes_processed / 1024 / 1024

        if duration_seconds > 0:
            bytes_per_second = bytes_processed / duration_seconds
            mb_per_second = mb_processed / duration_seconds
        else:
            bytes_per_second = float("inf")
            mb_per_second = float("inf")
    else:
        mb_processed = None
        bytes_per_second = None
        mb_per_second = None

    arguments = {
        "name": name,
        "status": status,
        "duration_seconds": duration_seconds,
        "bytes_processed": bytes_processed,
        "mb_processed": mb_processed,
        "bytes_per_second": bytes_per_second,
        "mb_per_second": mb_per_second,
    }
    if extra_arguments:
        arguments = {**arguments, **extra_arguments}

    try:
        logger.info(log_message, arguments)
    except:
        logger.exception(
            "Failed to log execution time with attributes '%s' and configuration '%s'",
            arguments,
            structlog.get_config(),
        )
