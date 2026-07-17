"""OTLP log push into the PostHog Logs product (the logs counterpart of `posthog/otel_metrics.py`).

`otel_log_mirror_processor(...)` is a structlog processor, not a stdlib `logging.Handler`: the Temporal
workers log through a non-stdlib structlog factory that a stdlib handler never sees. A no-op unless
OTLP_LOGS_INGEST_ENDPOINT and OTLP_LOGS_INGEST_TOKEN are set. Providers are lazy, per-process
(fork-safe), and keyed by service name, which becomes the `service.name` the Logs read side filters on.
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

_lock = threading.Lock()
_providers: "dict[str, LoggerProvider | None]" = {}
_providers_pid: int | None = None

_severity_by_levelno: "dict[int, tuple[str, SeverityNumber]] | None" = None

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
    """Logger name plus stringified allowlisted scalars. Fail-closed: non-allowlisted keys never ship."""
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
    """Structlog processor that mirrors records under `logger_prefix` into Logs over OTLP as
    `service.name`. Fail-soft, a no-op until OTLP_LOGS_INGEST_* are set, always fail-closed (only
    `attribute_allowlist` keys ship). Insert before the terminal renderer, message still under `event`.
    """
    allowlist = frozenset(attribute_allowlist)
    # Warm the provider at startup so the exporter's thread isn't spawned inside the workflow sandbox.
    _ensure_provider(service_name)

    # Resolve SDK types and the pinned resource once at startup (this factory runs after django.setup),
    # keeping them off the per-log path. Without a pinned resource the record would default to the pod's
    # OTEL_SERVICE_NAME and the Logs service.name filter would miss it.
    from opentelemetry.sdk._logs import LogRecord  # noqa: PLC0415
    from opentelemetry.sdk.resources import Resource  # noqa: PLC0415
    from opentelemetry.trace import TraceFlags  # noqa: PLC0415

    resource = Resource.create({"service.name": service_name})
    trace_flags = TraceFlags(TraceFlags.DEFAULT)

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

            level_name = event_dict.get("level") or method_name
            severity_text, severity_number = _severity(_LEVELNO_BY_LEVEL_NAME.get(level_name, logging.INFO))
            attributes = _scalar_attributes(event_dict, allowlist)
            attributes.update(_exception_type(event_dict))
            timestamp = time.time_ns()
            # Zero trace/span ids: the OTLP encoder serializes them as bytes and crashes on the default None.
            provider.get_logger(service_name, version="1").emit(
                LogRecord(
                    timestamp=timestamp,
                    observed_timestamp=timestamp,
                    trace_id=0,
                    span_id=0,
                    trace_flags=trace_flags,
                    severity_text=severity_text,
                    severity_number=severity_number,
                    body=str(event_dict.get("event", "")),
                    attributes=attributes,
                    resource=resource,
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
