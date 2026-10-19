import sys
import logging
import traceback

import structlog


def _resolve_exc_info(exc_info: object) -> BaseException | None:
    if exc_info is True:
        exc_info = sys.exc_info()
    if isinstance(exc_info, BaseException):
        return exc_info
    if isinstance(exc_info, tuple) and len(exc_info) == 3 and isinstance(exc_info[1], BaseException):
        return exc_info[1]
    return None


def _exception_type_name(exc: BaseException) -> str:
    exc_type = type(exc)
    if exc_type.__module__ == "builtins":
        return exc_type.__qualname__
    return f"{exc_type.__module__}.{exc_type.__qualname__}"


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
    exc = _resolve_exc_info(event_dict.pop("exc_info", None))
    if exc is None:
        return event_dict

    event_dict["exception.type"] = _exception_type_name(exc)
    event_dict["exception.message"] = _exception_message(exc)
    event_dict["exception.stacktrace"] = "".join(traceback.format_exception(exc))
    return event_dict
