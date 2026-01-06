import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Union

from prometheus_client import REGISTRY, CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from temporalio.runtime import (
    BUFFERED_METRIC_KIND_COUNTER,
    BUFFERED_METRIC_KIND_GAUGE,
    BUFFERED_METRIC_KIND_HISTOGRAM,
    BufferedMetricUpdate,
    MetricBuffer,
)

from posthog.temporal.common.logger import get_write_only_logger

logger = get_write_only_logger(__name__)

# Default histogram buckets suitable for Temporal metrics (in milliseconds when using MILLISECONDS format)
# These cover a wide range from 1ms to 24 hours
DEFAULT_HISTOGRAM_BUCKETS = (
    1.0,
    5.0,
    10.0,
    25.0,
    50.0,
    75.0,
    100.0,
    250.0,
    500.0,
    750.0,
    1000.0,
    2500.0,
    5000.0,
    7500.0,
    10000.0,
    30000.0,
    60000.0,
    300000.0,
    600000.0,
    900000.0,
    1800000.0,
    3600000.0,
    21600000.0,  # 6 hours
    43200000.0,  # 12 hours
    86400000.0,  # 24 hours
    float("inf"),
)


class TemporalMetricsCollector:
    """Collects metrics from Temporal's MetricBuffer and converts them to prometheus_client metrics."""

    def __init__(
        self,
        metric_buffer: MetricBuffer,
        metric_prefix: str = "",
        histogram_bucket_overrides: dict[str, tuple[float, ...]] | None = None,
        registry: CollectorRegistry | None = None,
    ):
        self._metric_buffer = metric_buffer
        self._metric_prefix = metric_prefix
        self._histogram_bucket_overrides = histogram_bucket_overrides or {}
        self._registry = registry or REGISTRY
        self._metrics: dict[str, Union[Counter, Gauge, Histogram]] = {}
        self._lock = threading.Lock()

    def _get_metric_key(self, name: str, label_names: tuple[str, ...]) -> str:
        return f"{self._metric_prefix}{name}:{','.join(sorted(label_names))}"

    def _get_or_create_metric(
        self,
        update: BufferedMetricUpdate,
        label_names: tuple[str, ...],
    ) -> Union[Counter, Gauge, Histogram]:
        """Get an existing metric or create a new one based on the update."""
        metric_name = f"{self._metric_prefix}{update.metric.name}"
        key = self._get_metric_key(update.metric.name, label_names)

        if key in self._metrics:
            return self._metrics[key]

        description = update.metric.description or f"Temporal metric: {update.metric.name}"
        kind = update.metric.kind

        if kind == BUFFERED_METRIC_KIND_COUNTER:
            self._metrics[key] = Counter(metric_name, description, labelnames=label_names, registry=self._registry)
        elif kind == BUFFERED_METRIC_KIND_GAUGE:
            self._metrics[key] = Gauge(metric_name, description, labelnames=label_names, registry=self._registry)
        elif kind == BUFFERED_METRIC_KIND_HISTOGRAM:
            buckets = self._histogram_bucket_overrides.get(update.metric.name, DEFAULT_HISTOGRAM_BUCKETS)
            self._metrics[key] = Histogram(
                metric_name,
                description,
                labelnames=label_names,
                buckets=buckets,
                registry=self._registry,
            )
        else:
            raise ValueError(f"Unknown metric kind: {kind}")

        return self._metrics[key]

    def collect_updates(self) -> None:
        """Pull metrics from the buffer and update prometheus_client metrics.

        This should be called before serving metrics to ensure fresh data.
        """
        with self._lock:
            try:
                updates = self._metric_buffer.retrieve_updates()
            except Exception as e:
                logger.warning("temporal_metrics_collector.retrieve_failed", error=str(e))
                return

            for update in updates:
                try:
                    label_names = tuple(sorted(update.attributes.keys()))
                    label_values = {k: str(v) for k, v in update.attributes.items()}

                    metric = self._get_or_create_metric(update, label_names)
                    kind = update.metric.kind

                    # Handle metrics with and without labels
                    if label_names:
                        labeled_metric = metric.labels(**label_values)
                    else:
                        labeled_metric = metric

                    if kind == BUFFERED_METRIC_KIND_COUNTER:
                        labeled_metric.inc(update.value)
                    elif kind == BUFFERED_METRIC_KIND_GAUGE:
                        labeled_metric.set(update.value)
                    elif kind == BUFFERED_METRIC_KIND_HISTOGRAM:
                        labeled_metric.observe(update.value)
                except Exception as e:
                    logger.warning(
                        "temporal_metrics_collector.update_failed",
                        metric_name=update.metric.name,
                        error=str(e),
                    )


class CombinedMetricsHandler(BaseHTTPRequestHandler):
    """HTTP handler that serves combined Temporal SDK and prometheus_client metrics."""

    temporal_collector: TemporalMetricsCollector | None = None
    registry: CollectorRegistry = REGISTRY

    def do_GET(self) -> None:
        if self.path in ("/metrics", "/"):
            self._serve_combined_metrics()
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_combined_metrics(self) -> None:
        try:
            # Collect latest Temporal metrics from the buffer before serving
            if self.temporal_collector:
                self.temporal_collector.collect_updates()

            # All metrics (Temporal + app) are now in prometheus_client registry
            output = generate_latest(self.registry)

            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.end_headers()
            self.wfile.write(output)

        except Exception as e:
            logger.exception("combined_metrics_server.error", error=str(e))
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f"Error: {e}".encode())

    def log_message(self, format: str, *args: object) -> None:
        pass


def start_combined_metrics_server(
    port: int,
    metric_buffer: MetricBuffer,
    metric_prefix: str = "",
    histogram_bucket_overrides: dict[str, tuple[float, ...]] | None = None,
    registry: CollectorRegistry | None = None,
) -> HTTPServer:
    """Start a metrics server combining Temporal SDK and prometheus_client metrics.

    This uses Temporal's MetricBuffer to access metrics directly without any HTTP
    calls. All metrics are served from a single prometheus_client registry.

    Args:
        port: Port to expose combined metrics on (e.g., 8001)
        metric_buffer: The MetricBuffer instance configured in Temporal's Runtime
        metric_prefix: Prefix to apply to Temporal metric names (e.g., "temporal_")
        histogram_bucket_overrides: Optional dict mapping metric names (without prefix)
            to custom bucket tuples for histogram metrics
        registry: Optional CollectorRegistry to use. Defaults to the global REGISTRY.
            Useful for test isolation.

    Returns:
        The HTTPServer instance
    """
    effective_registry = registry or REGISTRY
    collector = TemporalMetricsCollector(
        metric_buffer,
        metric_prefix=metric_prefix,
        histogram_bucket_overrides=histogram_bucket_overrides,
        registry=effective_registry,
    )

    handler = CombinedMetricsHandler
    handler.temporal_collector = collector
    handler.registry = effective_registry

    server = HTTPServer(("0.0.0.0", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="combined-metrics-server")
    thread.start()

    logger.info(
        "combined_metrics_server.started",
        port=port,
        metric_prefix=metric_prefix,
    )

    return server
