"""OTLP log push into the PostHog Logs product (first-party log dogfooding).

Ships structured logs through the same OTLP/HTTP path customers use, pointed at our own ingest
(the `capture-logs` service, path `/i/v1/logs`), authenticated with a project token. Off unless both
OTLP_LOGS_INGEST_ENDPOINT and OTLP_LOGS_INGEST_TOKEN are set, so nothing changes for deployments that
don't opt in. This is the logs counterpart of `posthog/otel_metrics.py`.

Attach `OtelLogHandler` to a stdlib logger (typically a product's namespace) to mirror that logger's
records into Logs without touching any log call sites; the existing console/JSON handlers keep working
alongside it. structlog routes through stdlib logging here, so this catches structlog output too.

Initialization is lazy and per-process (keyed on PID): preforking servers (gunicorn, celery) get a
live exporter thread in each worker instead of a dead one inherited from the parent, and no explicit
init call is needed. Providers are also keyed by service name, since `service.name` is a resource
attribute the Logs read side filters on, so each product's logs land under its own service.
"""

import os
import logging
import threading
from typing import TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:
    from opentelemetry._logs import SeverityNumber
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk.resources import Resource

_lock = threading.Lock()
_providers: "dict[str, LoggerProvider | None]" = {}
_providers_pid: int | None = None

_severity_by_levelno: "dict[int, tuple[str, SeverityNumber]] | None" = None


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

    # Deferred so the SDK + protobuf exporter stay off the django.setup() path; this only runs once
    # per (process, service) and only in deployments that opt in.
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter  # noqa: PLC0415
    from opentelemetry.sdk._logs import LoggerProvider  # noqa: PLC0415
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor  # noqa: PLC0415
    from opentelemetry.sdk.resources import Resource  # noqa: PLC0415

    from posthog.security.outbound_proxy import internal_requests_session  # noqa: PLC0415

    exporter = OTLPLogExporter(
        endpoint=settings.OTLP_LOGS_INGEST_ENDPOINT,
        headers={"authorization": f"Bearer {settings.OTLP_LOGS_INGEST_TOKEN}"},
        # capture-logs is in-cluster (a private ClusterIP); the export must bypass the Smokescreen
        # egress proxy or every batch silently 407s.
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


def _body_and_attributes(record: logging.LogRecord, allowlist: frozenset[str] | None) -> tuple[str, dict[str, str]]:
    """Extract a human message plus a stringified, scalar-only attribute map from a log record.

    The logs pipeline only indexes string-typed attributes into the queryable map, so every value
    is stringified and non-scalars are dropped. structlog's `ProcessorFormatter` path leaves the
    event dict on `record.msg` (the message under `event`, the rest structured fields); a plain
    stdlib record leaves a format string there instead.

    When `allowlist` is set the handler is fail-closed: only those event-dict keys are forwarded and
    the exception contributes just its type name, so payload-derived fields (model output previews,
    prompts, exception messages/tracebacks) never leave the emitting process. When it is None every
    scalar field and the full traceback are forwarded.
    """
    attributes: dict[str, str] = {"logger": record.name}
    msg = record.msg
    if isinstance(msg, dict):
        body = str(msg.get("event", ""))
        for key, value in msg.items():
            if key == "event" or (allowlist is not None and key not in allowlist):
                continue
            if isinstance(value, str | int | float | bool):
                attributes[key] = str(value)
    else:
        body = record.getMessage()
    if record.exc_info and record.exc_info[0] is not None:
        if allowlist is None:
            attributes["exception"] = logging.Formatter().formatException(record.exc_info)
        else:
            # Restricted mode: the class name is operational, but the message and traceback can embed
            # payload data, so ship only the type.
            attributes["exception_type"] = record.exc_info[0].__name__
    return body, attributes


class OtelLogHandler(logging.Handler):
    """A logging handler that mirrors each record into the PostHog Logs product over OTLP.

    Fail-soft and a no-op until OTLP_LOGS_INGEST_* are configured, so it is safe to attach
    unconditionally. `service_name` becomes the record's `service.name` resource — the field the Logs
    read side filters on. `static_attributes` ride every record (stringified).

    Pass `attribute_allowlist` to run fail-closed when the destination is a shared project: only those
    event-dict keys are forwarded (plus the logger name and, for exceptions, the type), so
    payload-derived fields never cross into it. Omit it to forward every scalar field.
    """

    def __init__(
        self,
        service_name: str,
        *,
        attribute_allowlist: set[str] | frozenset[str] | None = None,
        static_attributes: dict[str, str] | None = None,
        level: int = logging.INFO,
    ) -> None:
        super().__init__(level=level)
        self._service_name = service_name
        self._attribute_allowlist = frozenset(attribute_allowlist) if attribute_allowlist is not None else None
        self._static_attributes = {key: str(value) for key, value in (static_attributes or {}).items()}
        self._resource: Resource | None = None

    def emit(self, record: logging.LogRecord) -> None:
        # Swallow everything: a telemetry throw must never break the pipeline, and logging the
        # failure here would re-enter this handler for records under the same namespace (infinite
        # recursion). A dropped batch is at worst missing observability.
        try:
            provider = _ensure_provider(self._service_name)
            if provider is None:
                return

            from opentelemetry.sdk._logs import LogRecord  # noqa: PLC0415
            from opentelemetry.sdk.resources import Resource  # noqa: PLC0415

            if self._resource is None:
                self._resource = Resource.create({"service.name": self._service_name})

            body, extra = _body_and_attributes(record, self._attribute_allowlist)
            severity_text, severity_number = _severity(record.levelno)
            timestamp = int(record.created * 1_000_000_000)
            # Pin the resource on the record: Logger.emit attaches only the scope, and a LogRecord
            # built without resource= defaults to the pod's OTEL_SERVICE_NAME env, so the Logs read
            # filter (service.name = <service>) would never match. (engineering_analytics lesson.)
            provider.get_logger(self._service_name, version="1").emit(
                LogRecord(
                    timestamp=timestamp,
                    observed_timestamp=timestamp,
                    severity_text=severity_text,
                    severity_number=severity_number,
                    body=body,
                    attributes={**self._static_attributes, **extra},
                    resource=self._resource,
                )
            )
        except Exception:
            pass


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
