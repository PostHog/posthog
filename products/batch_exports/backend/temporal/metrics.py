import time
import typing
import asyncio
import datetime as dt

import structlog
from temporalio import activity, workflow
from temporalio.common import MetricCounter, MetricMeter
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    ExecuteWorkflowInput,
    Interceptor,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
)

from posthog.temporal.common.logger import get_write_only_logger

LOGGER = get_write_only_logger(__name__)


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


BATCH_EXPORT_ACTIVITY_TYPES = {
    "insert_into_internal_stage_activity",
    "insert_into_s3_activity_from_stage",
    "insert_into_snowflake_activity",
    "insert_into_snowflake_activity_from_stage",
    "insert_into_bigquery_activity",
    "insert_into_redshift_activity",
    "insert_into_postgres_activity",
    "insert_into_databricks_activity_from_stage",
}
BATCH_EXPORT_WORKFLOW_TYPES = {
    "s3-export",
    "bigquery-export",
    "snowflake-export",
    "redshift-export",
    "postgres-export",
    "databricks-export",
}

Attributes = dict[str, str | int | float | bool]


class BatchExportsMetricsInterceptor(Interceptor):
    """Interceptor to emit Prometheus metrics for batch exports."""

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _BatchExportsMetricsActivityInboundInterceptor(super().intercept_activity(next))

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> type[WorkflowInboundInterceptor] | None:
        return _BatchExportsMetricsWorkflowInterceptor


class _BatchExportsMetricsActivityInboundInterceptor(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> typing.Any:
        activity_info = activity.info()
        activity_type = activity_info.activity_type

        if activity_type not in BATCH_EXPORT_ACTIVITY_TYPES:
            return await super().execute_activity(input)

        interval = get_interval_from_bounds(input.args[0].data_interval_start, input.args[0].data_interval_end)
        if not interval:
            LOGGER.error(
                "Failed to parse interval bounds ('%s', '%s'), will not record latency for '%s'",
                input.args[0].data_interval_start,
                input.args[0].data_interval_end,
                activity_type,
            )
            return await super().execute_activity(input)

        histogram_attributes: Attributes = {
            "interval": interval,
        }

        meter = get_metric_meter(histogram_attributes)

        try:
            with ExecutionTimeRecorder(
                "batch_exports_activity_interval_execution_latency",
                description="Histogram tracking execution latency for critical batch export activities by interval",
                histogram_attributes=histogram_attributes,
                log=False,
            ):
                result = await super().execute_activity(input)
        finally:
            attempts_total_counter = meter.create_counter(
                name="batch_exports_activity_attempts",
                description="Counter tracking every attempt at running an activity",
            )
            attempts_total_counter.add(1)

        attempts_success_counter = meter.create_counter(
            name="batch_exports_activity_success_attempts",
            description="Counter tracking the attempts it took to complete activities",
        )
        attempts_success_counter.add(activity_info.attempt)

        return result


class _BatchExportsMetricsWorkflowInterceptor(WorkflowInboundInterceptor):
    async def execute_workflow(self, input: ExecuteWorkflowInput) -> typing.Any:
        workflow_info = workflow.info()
        workflow_type = workflow_info.workflow_type

        if workflow_type not in BATCH_EXPORT_WORKFLOW_TYPES:
            return await super().execute_workflow(input)

        # For consistency with the activity metric, use '_' as a separator instead of spaces.
        # This only affects "every 5 minutes" which becomes "every_5_minutes".
        interval = input.args[0].interval.replace(" ", "_")
        histogram_attributes: Attributes = {"interval": interval}

        async with SLAWaiter(batch_export_id=workflow_info.workflow_id, sla=get_sla_from_interval(interval)):
            with ExecutionTimeRecorder(
                "batch_exports_workflow_interval_execution_latency",
                description="Histogram tracking execution latency for batch export workflows by interval",
                histogram_attributes=histogram_attributes,
                log=False,
            ):
                return await super().execute_workflow(input)


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

        attributes = self.histogram_attributes or {}

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
            LOGGER.exception("Failed to record execution time to histogram '%s'", self.histogram_name)

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


def get_metric_meter(additional_attributes: Attributes | None = None) -> MetricMeter:
    """Return a meter depending on in which context we are."""
    if activity.in_activity():
        meter = activity.metric_meter()
    elif workflow.in_workflow():
        meter = workflow.metric_meter()
    else:
        raise RuntimeError("Not within workflow or activity context")

    if additional_attributes:
        meter = meter.with_additional_attributes(additional_attributes)

    return meter


def log_execution_time(
    log_message: str,
    name: str,
    delta: dt.timedelta,
    status: str,
    bytes_processed: None | int = None,
    extra_arguments: Attributes | None = None,
):
    """Log execution time."""
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
        LOGGER.info(log_message, arguments)
    except:
        LOGGER.exception(
            "Failed to log execution time with attributes '%s' and configuration '%s'",
            arguments,
            structlog.get_config(),
        )


def get_interval_from_bounds(
    data_interval_start: dt.datetime | None | str, data_interval_end: dt.datetime | str
) -> str | None:
    """Calculate the interval for a batch export based on its bounds."""
    if isinstance(data_interval_start, str):
        try:
            data_interval_start = dt.datetime.fromisoformat(data_interval_start)
        except ValueError:
            return None

    if isinstance(data_interval_end, str):
        try:
            data_interval_end = dt.datetime.fromisoformat(data_interval_end)
        except ValueError:
            return None

    if data_interval_start is None:
        interval = "beginning_of_time"
    else:
        match (data_interval_end - data_interval_start).total_seconds():
            case 3600.0:
                interval = "hour"
            case 86400.0:
                interval = "day"
            case 604800.0:
                interval = "week"
            case s:
                interval = f"every_{int(s / 60)}_minutes"

    return interval


def get_sla_from_interval(
    interval: str,
) -> dt.timedelta:
    """Get the SLA for a batch export based on its interval string."""
    match interval:
        case "hour":
            return dt.timedelta(hours=1)
        case "day":
            return dt.timedelta(days=1)
        case "week":
            return dt.timedelta(days=7)
        case interval:
            _, value, unit = interval.split("_")
            kwargs = {unit: int(value)}
            return dt.timedelta(**kwargs)


class SLAWaiter:
    """Wait until a batch export has exceeded SLA and log a warning.

    Attributes:
        batch_export_id: The batch export we are waiting for. Will be included in the
            log context if SLA is exceeded.
        sla: The SLA we are waiting for.

    Examples:
        Nothing happens when no SLA is exceeded.

        >>> async with SLAWaiter(batch_export_id="batch-export-id", sla=dt.timedelta(seconds=10)) as waiter:
        ...     await asyncio.sleep(1)
        ...     waiter.is_over_sla()
        False

        A log will be printed if SLA is exceeded.

        >>> async with SLAWaiter(batch_export_id="batch-export-id", sla=dt.timedelta(seconds=1)) as waiter:
        ...     await asyncio.sleep(10)
        ...     waiter.is_over_sla()
        True
    """

    def __init__(self, batch_export_id: str, sla: dt.timedelta):
        self.batch_export_id = batch_export_id
        self.sla = sla
        self._over_sla = asyncio.Event()
        self._waiter: asyncio.Task[None] | None = None

    def is_over_sla(self) -> bool:
        return self._over_sla.is_set()

    async def __aenter__(self) -> typing.Self:
        self._waiter = asyncio.create_task(self.wait_for_sla())
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback) -> None:
        """Reset internal state and cancel waiter."""

        if self._waiter:
            is_running = self._waiter.cancel()

            if is_running:
                _ = await asyncio.wait([self._waiter])

            self._waiter = None

        self._over_sla.clear()

    async def wait_for_sla(self) -> None:
        """Coroutine used to wait for SLA seconds."""
        await asyncio.sleep(self.sla.total_seconds())

        self._over_sla.set()
        LOGGER.warning(
            "SLA breached",
            batch_export_id=self.batch_export_id,
            sla_seconds=self.sla.total_seconds(),
        )
