import traceback

from temporalio.exceptions import ApplicationError, FailureError


class NonReportableError(Exception):
    """Marker for an expected, handled condition that must still fail the activity but should not
    be reported to error tracking. The activity interceptor re-raises these without capturing them,
    the same way it skips cancellations and egress backpressure. Subclass it for a failure that is
    always caused by the customer's config or the upstream API (never a PostHog defect) and that
    retrying can't resolve, so a tracked exception would only be noise."""


class NonReportableApplicationError(ApplicationError, NonReportableError):
    """An ApplicationError that must not be reported to error tracking.

    Behaves like any other ApplicationError to Temporal — it still fails the activity, honors the
    retry policy, and carries a `type` a workflow can branch on — but the activity interceptor's
    skip-list drops it via the NonReportableError marker instead of capturing it. Use it when an
    expected, handled condition needs to fail the activity as an ApplicationError yet would only be
    noise in error tracking (e.g. a short upstream outage the workflow already retries then fails
    open on)."""


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
