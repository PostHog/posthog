import time
import typing
import datetime as dt

from temporalio import activity, workflow
from temporalio.common import MetricMeter

from posthog.temporal.common.logger import get_write_only_logger

LOGGER = get_write_only_logger(__name__)

Attributes = dict[str, str | int | float | bool]


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


class ExecutionTimeRecorder:
    """Context manager to record execution time to a histogram metric."""

    def __init__(
        self,
        histogram_name: str,
        /,
        description: str | None = None,
        histogram_attributes: Attributes | None = None,
        log: bool = False,
    ) -> None:
        self.histogram_name = histogram_name
        self.description = description
        self.histogram_attributes = histogram_attributes or {}
        self.log = log
        self._start_counter: float | None = None
        self._status_override: str | None = None

    def set_status(self, status: str) -> None:
        """Override the status that will be recorded. Use for non-exception outcomes like SKIPPED."""
        self._status_override = status

    def __enter__(self) -> typing.Self:
        self._start_counter = time.perf_counter()
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback) -> None:
        if self._start_counter is None:
            raise RuntimeError("Start counter not initialized, did you call `__enter__`?")
        end_counter = time.perf_counter()
        delta_milli_seconds = int((end_counter - self._start_counter) * 1000)
        delta = dt.timedelta(milliseconds=delta_milli_seconds)
        attributes = dict(self.histogram_attributes)
        if exc_value is not None:
            attributes["status"] = "FAILED"
            # Class name, not str(exc): a free-form message would explode label cardinality.
            attributes["exception"] = type(exc_value).__name__
        elif self._status_override is not None:
            attributes["status"] = self._status_override
            attributes["exception"] = ""
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
            LOGGER.info(
                "Finished %s with status '%s' in %dms", self.histogram_name, attributes["status"], delta_milli_seconds
            )
        self._start_counter = None
