import traceback

from temporalio.exceptions import (
    ApplicationError,
    FailureError,
    TimeoutError as TemporalTimeoutError,
)


class NonReportableError(Exception):
    """Marker for an expected, handled condition that must still fail the activity but should not
    be reported to error tracking. The activity interceptor re-raises these without capturing them,
    the same way it skips cancellations and egress backpressure. Subclass it for a failure that is
    always caused by the customer's config or the upstream API (never a PostHog defect) and that
    retrying can't resolve, so a tracked exception would only be noise."""


# Bound error strings so a multi-MB str(e) (ClickHouse 5xx body, Playwright HTML dump)
# can't blow out Temporal's 2 MiB payload limit.
MAX_ERROR_MESSAGE_CHARS = 8_000
MAX_ERROR_TRACE_CHARS = 32_000


def truncate_for_temporal_payload(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}… (truncated, original {len(value)} chars)"


def unwrap_temporal_cause(exc: BaseException) -> ApplicationError | None:
    """Walk past Temporal's failure wrappers (ActivityError, ChildWorkflowError, …) to the underlying ApplicationError."""
    if isinstance(exc, ApplicationError):
        return None  # already at the leaf; nothing to unwrap
    current: BaseException | None = exc
    while isinstance(current, FailureError) and not isinstance(current, ApplicationError):
        current = current.cause
    return current if isinstance(current, ApplicationError) else None


def find_temporal_timeout_error(exc: BaseException) -> TemporalTimeoutError | None:
    current: BaseException | None = exc
    while isinstance(current, FailureError):
        if isinstance(current, TemporalTimeoutError):
            return current
        current = current.cause
    return None


def resolve_failure_type(exc: BaseException) -> str:
    """Temporal rebuilds a remote failure as a bare ApplicationError with the real class name on `.type`."""
    failure_type = getattr(exc, "type", None)
    if isinstance(failure_type, str) and failure_type:
        return failure_type
    return type(exc).__name__


def resolve_exception_class(exc: BaseException) -> str:
    cause: BaseException = unwrap_temporal_cause(exc) or exc
    return getattr(cause, "type", None) or type(cause).__name__


def describe_failure(exc: BaseException) -> str:
    """Name the exception that failed, for a record kept outside the worker logs.

    ``str()`` of an ``ActivityError`` is always "Activity task failed". ``ApplicationError`` prints
    its own ``type``, which Temporal sets to the original class name. A plain exception prints no
    type, so this function adds it. The result goes in a Temporal payload, so it has a size limit.
    """
    cause: BaseException = unwrap_temporal_cause(exc) or exc
    described = str(cause) if isinstance(cause, ApplicationError) else f"{type(cause).__name__}: {cause}"
    return truncate_for_temporal_payload(described, MAX_ERROR_MESSAGE_CHARS)


def resolve_error_trace(exc: BaseException) -> str:
    cause = unwrap_temporal_cause(exc)
    if cause is not None and cause.details and isinstance(cause.details[0], str):
        return truncate_for_temporal_payload(cause.details[0], MAX_ERROR_TRACE_CHARS)
    return truncate_for_temporal_payload("".join(traceback.format_exception(exc, limit=5)), MAX_ERROR_TRACE_CHARS)
