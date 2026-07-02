import traceback

from temporalio.exceptions import ApplicationError, FailureError

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


# Attribute flagging an exception as an expected, user-actionable failure (e.g. a customer-config
# error already surfaced to the customer) that must NOT be reported to error tracking when it
# crosses a Temporal activity/workflow boundary. Set it via `mark_expected_error`.
EXPECTED_ERROR_ATTR = "_posthog_expected_error"


def mark_expected_error(exc: BaseException) -> BaseException:
    """Flag `exc` as an expected, user-actionable failure so the PostHog Temporal interceptor
    skips reporting it to error tracking. The sync still fails and the message still reaches the
    customer — this only suppresses the internal, noisy error-tracking capture. Returns `exc` so it
    can be used inline: ``raise mark_expected_error(err)``."""
    try:
        setattr(exc, EXPECTED_ERROR_ATTR, True)
    except Exception:
        # Some builtin exceptions forbid arbitrary attributes; failing to tag just means the
        # error is captured as before, never that execution breaks.
        pass
    return exc


def is_expected_error(exc: BaseException) -> bool:
    """Whether `exc` is an expected, user-actionable failure that should not be reported to error
    tracking. True when it was flagged via `mark_expected_error`, or when it is a
    ``NonRetryableException`` — matched by class name to avoid importing product code, and because
    that type already signals a classified, customer-surfaced config failure rather than a defect."""
    if getattr(exc, EXPECTED_ERROR_ATTR, False):
        return True
    return type(exc).__name__ == "NonRetryableException"
