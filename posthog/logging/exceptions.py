import sys
import logging
import traceback
from types import TracebackType

import structlog


def _resolve_exc_info(exc_info: object) -> tuple[BaseException, TracebackType | None] | None:
    if exc_info is True:
        exc_info = sys.exc_info()
    if isinstance(exc_info, BaseException):
        return exc_info, exc_info.__traceback__
    # The caller can capture the tuple before the exception's `__traceback__` changes, so keep its traceback.
    if isinstance(exc_info, tuple) and len(exc_info) == 3 and isinstance(exc_info[1], BaseException):
        return exc_info[1], exc_info[2]
    return None


def _exception_message(exc: BaseException) -> str:
    try:
        return str(exc)
    except Exception:
        # Same fallback as `traceback.format_exception`. A raising processor drops the record, and in the
        # Temporal chain the error escapes into the caller's error handling.
        return "<exception str() failed>"


def add_otel_exception_attributes(
    logger: logging.Logger, method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    # https://opentelemetry.io/docs/specs/semconv/exceptions/exceptions-logs/
    # The collector stores each top-level JSON key as one log attribute, so the keys keep their dots.
    resolved = _resolve_exc_info(event_dict.pop("exc_info", None))
    if resolved is None:
        return event_dict
    exc, tb = resolved

    # The bare class name matches what the OTel Python SDK `LoggingHandler` writes, although the spec asks
    # for a qualified name. Services that log through the SDK then group with these logs.
    event_dict["exception.type"] = type(exc).__name__
    event_dict["exception.message"] = _exception_message(exc)
    event_dict["exception.stacktrace"] = "".join(traceback.format_exception(type(exc), exc, tb))
    return event_dict
