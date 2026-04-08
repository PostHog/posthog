"""Shared helpers for inspecting Temporal's ``ActivityError → ApplicationError`` exception chain."""

import traceback

from temporalio.exceptions import ActivityError, ApplicationError


def unwrap_temporal_cause(exc: BaseException) -> ApplicationError | None:
    """Return the ``ApplicationError`` cause of a Temporal ``ActivityError``, or ``None`` if ``exc`` isn't one."""
    if isinstance(exc, ActivityError) and isinstance(exc.cause, ApplicationError):
        return exc.cause
    return None


def resolve_exception_class(exc: BaseException) -> str:
    """Return the exception class name, preferring ``ApplicationError.type`` over the Python class name."""
    cause: BaseException = unwrap_temporal_cause(exc) or exc
    return getattr(cause, "type", None) or type(cause).__name__


def resolve_error_trace(exc: BaseException) -> str:
    """Return a stack trace, preferring the activity-side trace stashed in ``ApplicationError.details[0]``."""
    cause = unwrap_temporal_cause(exc)
    if cause is not None and cause.details and isinstance(cause.details[0], str):
        return cause.details[0]
    return "".join(traceback.format_exception(exc, limit=5))
