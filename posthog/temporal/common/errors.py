import traceback

from temporalio.exceptions import ApplicationError, FailureError


class NonRetryableError(Exception):
    """Base for deliberate "give up — the user must fix their config" signals raised by
    Temporal activities (bad credentials, a plan/scope gap, a dead host).

    These are expected control flow, not defects: the pipeline has exhausted its retries and
    wants the job marked failed with a helpful message. The PostHog interceptor treats them
    like cancellations — it skips reporting them to error tracking — so they don't spawn a
    fresh error-tracking issue for a failure nobody can act on."""

    @property
    def cause(self) -> BaseException | None:
        """Cause of the exception. Same as ``Exception.__cause__``."""
        return self.__cause__


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
