import traceback

from temporalio.exceptions import ActivityError, ApplicationError


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
        return cause.details[0]
    return "".join(traceback.format_exception(exc, limit=5))
