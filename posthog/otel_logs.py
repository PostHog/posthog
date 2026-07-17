"""OTLP log push into the PostHog Logs product (the logs counterpart of `posthog/otel_metrics.py`).

`otel_log_mirror_processor(...)` returns a structlog processor that mirrors matching records into the
Logs product over OTLP. It is a structlog processor rather than a stdlib `logging.Handler` because the
Temporal workers configure structlog with a non-stdlib logger factory that bypasses stdlib logging, so
a handler attached to a stdlib logger never sees their records. A no-op unless OTLP_LOGS_INGEST_ENDPOINT
and OTLP_LOGS_INGEST_TOKEN are set. Providers are lazy and per-process (fork-safe) and keyed by service
name, which becomes the `service.name` the Logs read side filters on.
"""

import os
import sys
import time
import logging
import threading
from typing import TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:
    import structlog
    from opentelemetry._logs import SeverityNumber
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk.resources import Resource

_lock = threading.Lock()
_providers: "dict[str, LoggerProvider | None]" = {}
_providers_pid: int | None = None

_severity_by_levelno: "dict[int, tuple[str, SeverityNumber]] | None" = None

# `add_log_level` writes the lowercase level name (and structlog's method name matches) to a levelno.
_LEVELNO_BY_LEVEL_NAME = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "warn": logging.WARNING,
    "error": logging.ERROR,
    "exception": logging.ERROR,
    "critical": logging.CRITICAL,
    "fatal": logging.CRITICAL,
}


def _ensure_provider(service_name: str) -> "LoggerProvider | None":
    global _providers, _providers_pid
    pid = os.getpid()
    with _lock:
        if _providers_pid != pid:
            _providers = {}
            _providers_pid = pid
        if service_name not in _providers:
            _providers[service_name] = _build_provider(service_name)
        return _providers[service_name]


def _build_provider(service_name: str) -> "LoggerProvider | None":
    if not settings.OTLP_LOGS_INGEST_ENDPOINT or not settings.OTLP_LOGS_INGEST_TOKEN:
        return None

    # Deferred to keep the OTLP SDK off the django.setup() path.
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter  # noqa: PLC0415
    from opentelemetry.sdk._logs import LoggerProvider  # noqa: PLC0415
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor  # noqa: PLC0415
    from opentelemetry.sdk.resources import Resource  # noqa: PLC0415

    from posthog.security.outbound_proxy import internal_requests_session  # noqa: PLC0415

    exporter = OTLPLogExporter(
        endpoint=settings.OTLP_LOGS_INGEST_ENDPOINT,
        headers={"authorization": f"Bearer {settings.OTLP_LOGS_INGEST_TOKEN}"},
        # Bypass the Smokescreen egress proxy (capture-logs is a private ClusterIP it 407s).
        session=internal_requests_session(),
    )
    provider = LoggerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
    return provider


def _severity(levelno: int) -> "tuple[str, SeverityNumber]":
    global _severity_by_levelno
    if _severity_by_levelno is None:
        from opentelemetry._logs import SeverityNumber  # noqa: PLC0415

        _severity_by_levelno = {
            logging.DEBUG: ("DEBUG", SeverityNumber.DEBUG),
            logging.INFO: ("INFO", SeverityNumber.INFO),
            logging.WARNING: ("WARN", SeverityNumber.WARN),
            logging.ERROR: ("ERROR", SeverityNumber.ERROR),
            logging.CRITICAL: ("FATAL", SeverityNumber.FATAL),
        }
    return _severity_by_levelno.get(levelno, _severity_by_levelno[logging.INFO])


def _scalar_attributes(event_dict: "structlog.types.EventDict", allowlist: frozenset[str]) -> dict[str, str]:
    """The logger name plus the stringified allowlisted scalar fields. Fail-closed: only allowlisted
    keys ship, so payload-derived fields (previews, prompts) stay in the process."""
    attributes: dict[str, str] = {}
    name = event_dict.get("logger")
    if name:
        attributes["logger"] = str(name)
    for key, value in event_dict.items():
        if key in ("event", "logger", "exc_info") or key not in allowlist:
            continue
        if isinstance(value, str | int | float | bool):
            attributes[key] = str(value)
    return attributes


def _exception_type(event_dict: "structlog.types.EventDict") -> dict[str, str]:
    """Only the exception's type name. The message and traceback can embed payload data."""
    exc_info = event_dict.get("exc_info")
    if not exc_info:
        return {}
    if exc_info is True:
        exc_info = sys.exc_info()
    if isinstance(exc_info, BaseException):
        return {"exception_type": type(exc_info).__name__}
    if isinstance(exc_info, tuple) and exc_info and exc_info[0] is not None:
        return {"exception_type": exc_info[0].__name__}
    return {}


def otel_log_mirror_processor(
    service_name: str,
    *,
    logger_prefix: str,
    attribute_allowlist: "set[str] | frozenset[str]",
) -> "structlog.types.Processor":
    """Return a structlog processor that mirrors matching records into the Logs product over OTLP.

    Only records whose logger name starts with `logger_prefix` are mirrored, under
    `service.name = service_name`. Fail-soft and a no-op until OTLP_LOGS_INGEST_* are configured. It is
    always fail-closed: only `attribute_allowlist` keys ship, and an exception contributes just its
    type. Insert it before the terminal renderer, while the event dict is still structured and the
    message is under `event`.
    """
    allowlist = frozenset(attribute_allowlist)
    resource: list[Resource | None] = [None]
    # Warm the provider now (worker startup, outside the Temporal workflow sandbox) so the
    # BatchLogRecordProcessor background thread is never spawned lazily during a workflow task.
    _ensure_provider(service_name)

    def mirror(
        logger: "structlog.types.WrappedLogger",
        method_name: str,
        event_dict: "structlog.types.EventDict",
    ) -> "structlog.types.EventDict":
        # Fail-soft: telemetry must never break the pipeline, and never log here (it would recurse).
        try:
            name = event_dict.get("logger") or getattr(logger, "name", "") or ""
            if not name.startswith(logger_prefix):
                return event_dict
            provider = _ensure_provider(service_name)
            if provider is None:
                return event_dict

            from opentelemetry.sdk._logs import LogRecord  # noqa: PLC0415
            from opentelemetry.sdk.resources import Resource  # noqa: PLC0415

            if resource[0] is None:
                # Pin the resource: a record built without it defaults to the pod's OTEL_SERVICE_NAME,
                # so the Logs filter on service.name would miss these records.
                resource[0] = Resource.create({"service.name": service_name})

            level_name = event_dict.get("level") or method_name
            severity_text, severity_number = _severity(_LEVELNO_BY_LEVEL_NAME.get(level_name, logging.INFO))
            attributes = _scalar_attributes(event_dict, allowlist)
            attributes.update(_exception_type(event_dict))
            timestamp = time.time_ns()
            provider.get_logger(service_name, version="1").emit(
                LogRecord(
                    timestamp=timestamp,
                    observed_timestamp=timestamp,
                    severity_text=severity_text,
                    severity_number=severity_number,
                    body=str(event_dict.get("event", "")),
                    attributes=attributes,
                    resource=resource[0],
                )
            )
        except Exception:
            pass
        return event_dict

    return mirror


def reset_otel_logs_for_tests() -> None:
    """Shut down and forget cached providers so a test can exercise gating with patched settings."""
    global _providers, _providers_pid, _severity_by_levelno
    with _lock:
        for provider in _providers.values():
            if provider is not None:
                provider.shutdown()
        _providers = {}
        _providers_pid = None
        _severity_by_levelno = None
