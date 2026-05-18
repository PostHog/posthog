import traceback

from temporalio.exceptions import ActivityError, ApplicationError

# Bound error strings so a multi-MB str(e) (ClickHouse 5xx body, Playwright HTML dump)
# can't blow out Temporal's 2 MiB payload limit.
MAX_ERROR_MESSAGE_CHARS = 8_000
MAX_ERROR_TRACE_CHARS = 32_000


def truncate_for_temporal_payload(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}… (truncated, original {len(value)} chars)"


def unwrap_temporal_cause(exc: BaseException) -> ApplicationError | None:
    if isinstance(exc, ActivityError) and isinstance(exc.cause, ApplicationError):
        return exc.cause
    return None


def resolve_exception_class(exc: BaseException) -> str:
    cause: BaseException = unwrap_temporal_cause(exc) or exc
    return getattr(cause, "type", None) or type(cause).__name__


def resolve_error_trace(exc: BaseException) -> str:
    cause = unwrap_temporal_cause(exc)
    if cause is not None and cause.details and isinstance(cause.details[0], str):
        return truncate_for_temporal_payload(cause.details[0], MAX_ERROR_TRACE_CHARS)
    return truncate_for_temporal_payload("".join(traceback.format_exception(exc, limit=5)), MAX_ERROR_TRACE_CHARS)
