"""OTLP metrics push into the PostHog Metrics product (Python twin of nodejs/src/common/metrics/otel-metrics.ts).

Pushes metrics through the same OTel-SDK path customers use, pointed at our own ingest
(the `capture-logs` service, path `/i/v1/metrics`), authenticated with a project token.
Off unless both OTEL_METRICS_EXPORT_URL and OTEL_METRICS_EXPORT_TOKEN are set, so nothing
changes for deployments that don't opt in. This complements Prometheus instrumentation
(scraped, Grafana) rather than replacing it. Callers keep emitting the same metric names
to both so dashboards translate 1:1.

Initialization is lazy and per-process (keyed on PID): preforking servers (gunicorn,
celery) get a live exporter thread in each worker instead of a dead one inherited from
the parent, and no explicit init call is needed anywhere.
"""

import os
import socket
import threading
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from django.conf import settings

from opentelemetry.metrics import Counter, Histogram, Meter, NoOpMeter, _Gauge
from prometheus_client import (
    Counter as PromCounter,
    Gauge as PromGauge,
    Histogram as PromHistogram,
)

if TYPE_CHECKING:
    from opentelemetry.sdk.metrics import MeterProvider

_lock = threading.Lock()
_provider: "MeterProvider | None" = None
_provider_pid: int | None = None


def get_otel_meter(name: str) -> Meter:
    """Return a meter bound to the OTLP-push provider, initializing it on first use.

    Without both env vars this returns a no-op meter, so recording is free and safe
    everywhere. Prefer `OtelInstrumentFactory` over calling this directly: instruments
    must be cached (re-creating them per record triggers SDK duplicate warnings), and
    the factory handles that plus fork safety.
    """
    global _provider, _provider_pid
    pid = os.getpid()
    if _provider_pid != pid:
        with _lock:
            if _provider_pid != pid:
                _provider = _build_provider()
                _provider_pid = pid
    if _provider is None:
        return NoOpMeter(name)
    return _provider.get_meter(name)


def _build_provider() -> "MeterProvider | None":
    if not settings.OTEL_METRICS_EXPORT_URL or not settings.OTEL_METRICS_EXPORT_TOKEN:
        return None

    # Deferred so the SDK + protobuf exporter stay off the django.setup() path; this only
    # runs once per process, and only in deployments that opt in.
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter  # noqa: PLC0415
    from opentelemetry.sdk.metrics import MeterProvider  # noqa: PLC0415
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader  # noqa: PLC0415
    from opentelemetry.sdk.resources import Resource  # noqa: PLC0415

    from posthog.security.outbound_proxy import internal_requests_session  # noqa: PLC0415

    exporter = OTLPMetricExporter(
        endpoint=settings.OTEL_METRICS_EXPORT_URL,
        headers={"authorization": f"Bearer {settings.OTEL_METRICS_EXPORT_TOKEN}"},
        # capture-logs is in-cluster (a private ClusterIP); the export must bypass the
        # Smokescreen egress proxy or every batch silently 407s.
        session=internal_requests_session(),
    )
    resource = Resource.create(
        {
            "service.name": os.environ.get("OTEL_SERVICE_NAME") or "posthog-python",
            "service.version": os.environ.get("COMMIT_SHA") or "dev",
            # Per-process identity. Without it every worker process shares one series, and
            # their interleaved cumulative counters read as constant resets. rate() and
            # increase() would overcount by roughly the process count.
            "service.instance.id": f"{socket.gethostname()}-{os.getpid()}",
        }
    )
    return MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(exporter, export_interval_millis=settings.OTEL_METRICS_EXPORT_INTERVAL_MS)
        ],
    )


class OtelInstrumentFactory:
    """Per-process lazy instrument cache for one meter.

    Products declare a module-level factory and fetch instruments by name at record time.
    Instruments are created on first use, after the provider exists. The OTel API has no
    proxy provider, so instruments created at module import would bind to the no-op meter
    forever. The cache is dropped on fork so children rebuild against a live provider.
    """

    def __init__(self, meter_name: str) -> None:
        self._meter_name = meter_name
        self._pid: int | None = None
        self._cache: dict[str, Any] = {}
        self._cache_lock = threading.Lock()

    def counter(self, name: str, *, description: str = "", unit: str = "") -> Counter:
        return self._get(name, lambda meter: meter.create_counter(name, unit=unit, description=description))

    def histogram(
        self,
        name: str,
        *,
        description: str = "",
        unit: str = "",
        boundaries: Sequence[float] | None = None,
    ) -> Histogram:
        return self._get(
            name,
            lambda meter: meter.create_histogram(
                name,
                unit=unit,
                description=description,
                explicit_bucket_boundaries_advisory=list(boundaries) if boundaries is not None else None,
            ),
        )

    def gauge(self, name: str, *, description: str = "", unit: str = "") -> _Gauge:
        return self._get(name, lambda meter: meter.create_gauge(name, unit=unit, description=description))

    # The record_*_twin methods mirror an existing Prometheus instrument into the Metrics
    # product, deriving name and description from the instrument itself so the two sinks
    # can't drift. They swallow all errors: twins run in hot paths and error handlers,
    # where a telemetry throw would mask the real failure.

    def record_counter_twin(self, metric: PromCounter, value: float, attributes: dict[str, str]) -> None:
        try:
            described = next(iter(metric.describe()))
            # prometheus_client strips _total from counter names internally and re-appends
            # it on scraped samples; restore it so the OTLP name matches the scraped name.
            self.counter(f"{described.name}_total", description=described.documentation).add(value, attributes)
        except Exception:
            pass

    def record_histogram_twin(
        self,
        metric: PromHistogram,
        value: float,
        attributes: dict[str, str],
        *,
        boundaries: Sequence[float] | None = None,
    ) -> None:
        try:
            described = next(iter(metric.describe()))
            self.histogram(described.name, description=described.documentation, unit="s", boundaries=boundaries).record(
                value, attributes
            )
        except Exception:
            pass

    def record_gauge_twin(self, metric: PromGauge, value: float) -> None:
        try:
            described = next(iter(metric.describe()))
            self.gauge(described.name, description=described.documentation).set(value)
        except Exception:
            pass

    def _get(self, name: str, build: Callable[[Meter], Any]) -> Any:
        pid = os.getpid()
        if self._pid != pid:
            with self._cache_lock:
                if self._pid != pid:
                    self._cache = {}
                    self._pid = pid
        instrument = self._cache.get(name)
        if instrument is None:
            with self._cache_lock:
                instrument = self._cache.get(name)
                if instrument is None:
                    instrument = build(get_otel_meter(self._meter_name))
                    self._cache[name] = instrument
        return instrument


def reset_otel_metrics_for_tests() -> None:
    """Shut down and forget the cached provider so a test can exercise gating with patched settings."""
    global _provider, _provider_pid
    with _lock:
        if _provider is not None:
            _provider.shutdown()
        _provider = None
        _provider_pid = None
