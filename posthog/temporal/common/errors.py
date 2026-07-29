import traceback
from typing import TypeVar

from temporalio.exceptions import ApplicationError, FailureError


class NonReportableError(Exception):
    """Marker for an expected, handled condition that must still fail the activity but should not
    be reported to error tracking. The activity interceptor re-raises these without capturing them,
    the same way it skips cancellations and egress backpressure. Subclass it for a failure that is
    always caused by the customer's config or the upstream API (never a PostHog defect) and that
    retrying can't resolve, so a tracked exception would only be noise."""


class NonReportableRetryableError(Exception):
    """Marker for the case NonReportableError deliberately excludes: a transient upstream condition
    (a rate limit whose in-process retry budget ran out, a 5xx blip) that must fail the activity so
    Temporal retries it, but that clears on its own and so is only noise in error tracking.

    A sibling of NonReportableError rather than a subclass, because that marker is scoped to
    failures retrying can never resolve and callers branch on that distinction. Subclass this when
    the condition is knowable from the exception type; when it is classified at the catch site
    instead (matching an arbitrary upstream exception against a source's retryable-message list),
    flag the instance with mark_non_reportable."""


_NON_REPORTABLE_ATTR = "_posthog_non_reportable"

ExceptionT = TypeVar("ExceptionT", bound=BaseException)


def mark_non_reportable(error: ExceptionT) -> ExceptionT:
    """Flag an exception instance so the activity interceptor re-raises it without capturing it.

    For a failure whose reportability is decided by the code that catches it rather than by its
    type. Returns the error so it can be flagged inline at the ``raise`` site."""
    setattr(error, _NON_REPORTABLE_ATTR, True)
    return error


def is_non_reportable(error: BaseException) -> bool:
    """Whether an exception escaping an activity must be kept out of error tracking, either by
    marker class or because it was flagged with mark_non_reportable."""
    if isinstance(error, NonReportableError | NonReportableRetryableError):
        return True
    return getattr(error, _NON_REPORTABLE_ATTR, False) is True


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


def resolve_exception_class(exc: BaseException) -> str:
    cause: BaseException = unwrap_temporal_cause(exc) or exc
    return getattr(cause, "type", None) or type(cause).__name__


def resolve_error_trace(exc: BaseException) -> str:
    cause = unwrap_temporal_cause(exc)
    if cause is not None and cause.details and isinstance(cause.details[0], str):
        return truncate_for_temporal_payload(cause.details[0], MAX_ERROR_TRACE_CHARS)
    return truncate_for_temporal_payload("".join(traceback.format_exception(exc, limit=5)), MAX_ERROR_TRACE_CHARS)
