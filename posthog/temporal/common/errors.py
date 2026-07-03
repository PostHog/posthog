import traceback
from typing import Any

from temporalio.exceptions import ApplicationError, FailureError

# Bound error strings so a multi-MB str(e) (ClickHouse 5xx body, Playwright HTML dump)
# can't blow out Temporal's 2 MiB payload limit.
MAX_ERROR_MESSAGE_CHARS = 8_000
MAX_ERROR_TRACE_CHARS = 32_000

# Marker attribute flagging an ApplicationError as an expected, self-healing condition — one that
# Temporal's retry/backoff absorbs and that must NOT surface as an error-tracking issue. The shared
# PostHog activity interceptor honors it (the same way it already skips cancellations), so a benign
# retryable denial (e.g. shared egress backpressure) drives a retry without minting noisy occurrences.
_BENIGN_RETRY_ATTR = "_posthog_benign_retry"


def benign_retry_error(message: str, *, type: str, **kwargs: Any) -> ApplicationError:
    """An ``ApplicationError`` that still triggers Temporal's retry but is flagged so the PostHog
    interceptor skips error-tracking capture. Use for expected, retryable backpressure that
    self-heals — not for real faults, which must still surface."""
    error = ApplicationError(message, type=type, **kwargs)
    setattr(error, _BENIGN_RETRY_ATTR, True)
    return error


def is_benign_retry_error(exc: BaseException) -> bool:
    """Whether ``exc`` was flagged benign by :func:`benign_retry_error`."""
    return getattr(exc, _BENIGN_RETRY_ATTR, False) is True


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
