import socket
import urllib.error
import urllib.request

import pytest
from unittest.mock import MagicMock

from prometheus_client import REGISTRY, Counter
from temporalio.runtime import (
    BUFFERED_METRIC_KIND_COUNTER,
    BUFFERED_METRIC_KIND_GAUGE,
    BUFFERED_METRIC_KIND_HISTOGRAM,
    MetricBuffer,
)

from posthog.temporal.common.combined_metrics_server import (
    DEFAULT_HISTOGRAM_BUCKETS,
    TemporalMetricsCollector,
    start_combined_metrics_server,
)


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def create_mock_metric_update(name: str, kind: int, value: float, attributes: dict[str, str] | None = None):
    """Create a mock BufferedMetricUpdate."""
    mock_metric = MagicMock()
    mock_metric.name = name
    mock_metric.description = f"Description for {name}"
    mock_metric.unit = "ms"
    mock_metric.kind = kind

    mock_update = MagicMock()
    mock_update.metric = mock_metric
    mock_update.value = value
    mock_update.attributes = attributes or {}

    return mock_update


@pytest.fixture
def mock_metric_buffer():
    """Create a mock MetricBuffer that returns simulated metrics."""
    buffer = MagicMock(spec=MetricBuffer)
    buffer.retrieve_updates.return_value = [
        create_mock_metric_update("workflow_completed", BUFFERED_METRIC_KIND_COUNTER, 42, {"namespace": "default"}),
        create_mock_metric_update("active_workers", BUFFERED_METRIC_KIND_GAUGE, 5, {"task_queue": "main"}),
    ]
    return buffer


@pytest.fixture
def test_counter():
    """Create a test prometheus_client counter."""
    counter_name = f"test_counter_{get_free_port()}"
    counter = Counter(counter_name, "A test counter for combined metrics")
    counter.inc()
    yield counter_name
    try:
        REGISTRY.unregister(counter)
    except Exception:
        pass


class TestTemporalMetricsCollector:
    def test_collects_counter_metrics(self):
        unique_prefix = f"tc_{get_free_port()}_"
        buffer = MagicMock(spec=MetricBuffer)
        buffer.retrieve_updates.return_value = [
            create_mock_metric_update("counter", BUFFERED_METRIC_KIND_COUNTER, 10, {"label": "value"}),
        ]

        collector = TemporalMetricsCollector(buffer, metric_prefix=unique_prefix)
        collector.collect_updates()

        assert f"{unique_prefix}counter:label" in collector._metrics
        metric = collector._metrics[f"{unique_prefix}counter:label"]
        assert metric._name == f"{unique_prefix}counter"

    def test_collects_gauge_metrics(self):
        unique_prefix = f"tg_{get_free_port()}_"
        buffer = MagicMock(spec=MetricBuffer)
        buffer.retrieve_updates.return_value = [
            create_mock_metric_update("gauge", BUFFERED_METRIC_KIND_GAUGE, 25.5, {"host": "worker1"}),
        ]

        collector = TemporalMetricsCollector(buffer, metric_prefix=unique_prefix)
        collector.collect_updates()

        assert f"{unique_prefix}gauge:host" in collector._metrics

    def test_collects_histogram_metrics(self):
        unique_prefix = f"th_{get_free_port()}_"
        buffer = MagicMock(spec=MetricBuffer)
        buffer.retrieve_updates.return_value = [
            create_mock_metric_update("histogram", BUFFERED_METRIC_KIND_HISTOGRAM, 150.0, {}),
        ]

        collector = TemporalMetricsCollector(buffer, metric_prefix=unique_prefix)
        collector.collect_updates()

        assert f"{unique_prefix}histogram:" in collector._metrics

    def test_handles_empty_buffer(self):
        unique_prefix = f"te_{get_free_port()}_"
        buffer = MagicMock(spec=MetricBuffer)
        buffer.retrieve_updates.return_value = []

        collector = TemporalMetricsCollector(buffer, metric_prefix=unique_prefix)
        collector.collect_updates()

        assert len(collector._metrics) == 0

    def test_handles_buffer_error(self):
        unique_prefix = f"terr_{get_free_port()}_"
        buffer = MagicMock(spec=MetricBuffer)
        buffer.retrieve_updates.side_effect = RuntimeError("Buffer error")

        collector = TemporalMetricsCollector(buffer, metric_prefix=unique_prefix)
        collector.collect_updates()

        assert len(collector._metrics) == 0

    def test_accumulates_counter_increments(self):
        unique_prefix = f"tacc_{get_free_port()}_"
        buffer = MagicMock(spec=MetricBuffer)
        buffer.retrieve_updates.return_value = [
            create_mock_metric_update("accumulated", BUFFERED_METRIC_KIND_COUNTER, 5, {}),
        ]

        collector = TemporalMetricsCollector(buffer, metric_prefix=unique_prefix)
        collector.collect_updates()

        buffer.retrieve_updates.return_value = [
            create_mock_metric_update("accumulated", BUFFERED_METRIC_KIND_COUNTER, 3, {}),
        ]
        collector.collect_updates()

        metric = collector._metrics[f"{unique_prefix}accumulated:"]
        # Counter should have been incremented twice (5 + 3 = 8)
        assert metric._value.get() == 8.0


class TestCombinedMetricsServer:
    def test_serves_combined_metrics(self, mock_metric_buffer, test_counter):
        port = get_free_port()
        # Use unique prefix to avoid conflicts with other tests
        unique_prefix = f"test_{port}_"

        server = start_combined_metrics_server(
            port=port,
            metric_buffer=mock_metric_buffer,
            metric_prefix=unique_prefix,
        )

        try:
            url = f"http://127.0.0.1:{port}/metrics"
            with urllib.request.urlopen(url, timeout=5) as response:
                content = response.read().decode("utf-8")

            # Check Temporal metrics from buffer (with unique prefix)
            assert f"{unique_prefix}workflow_completed" in content
            assert f"{unique_prefix}active_workers" in content
            # Check prometheus_client metrics
            assert test_counter in content
        finally:
            server.shutdown()

    def test_serves_metrics_when_buffer_empty(self, test_counter):
        port = get_free_port()
        empty_buffer = MagicMock(spec=MetricBuffer)
        empty_buffer.retrieve_updates.return_value = []
        # Use unique prefix that won't match any existing metrics
        unique_prefix = f"empty_test_{port}_"

        server = start_combined_metrics_server(
            port=port,
            metric_buffer=empty_buffer,
            metric_prefix=unique_prefix,
        )

        try:
            url = f"http://127.0.0.1:{port}/metrics"
            with urllib.request.urlopen(url, timeout=5) as response:
                content = response.read().decode("utf-8")

            # No metrics with our unique prefix since buffer is empty
            assert f"{unique_prefix}" not in content
            # But prometheus_client metrics should still be there
            assert test_counter in content
        finally:
            server.shutdown()

    def test_returns_404_for_unknown_paths(self, mock_metric_buffer):
        port = get_free_port()
        unique_prefix = f"test404_{port}_"

        server = start_combined_metrics_server(
            port=port,
            metric_buffer=mock_metric_buffer,
            metric_prefix=unique_prefix,
        )

        try:
            url = f"http://127.0.0.1:{port}/unknown"
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(url, timeout=5)

            assert exc_info.value.code == 404
        finally:
            server.shutdown()

    def test_root_path_serves_metrics(self, mock_metric_buffer, test_counter):
        port = get_free_port()
        unique_prefix = f"testroot_{port}_"

        server = start_combined_metrics_server(
            port=port,
            metric_buffer=mock_metric_buffer,
            metric_prefix=unique_prefix,
        )

        try:
            url = f"http://127.0.0.1:{port}/"
            with urllib.request.urlopen(url, timeout=5) as response:
                content = response.read().decode("utf-8")

            assert f"{unique_prefix}workflow_completed" in content
            assert test_counter in content
        finally:
            server.shutdown()


class TestDefaultHistogramBuckets:
    def test_buckets_cover_wide_range(self):
        assert DEFAULT_HISTOGRAM_BUCKETS[0] == 1.0  # 1ms
        assert DEFAULT_HISTOGRAM_BUCKETS[-1] == float("inf")
        assert 3600000.0 in DEFAULT_HISTOGRAM_BUCKETS  # 1 hour in ms

    def test_buckets_are_sorted(self):
        finite_buckets = [b for b in DEFAULT_HISTOGRAM_BUCKETS if b != float("inf")]
        assert finite_buckets == sorted(finite_buckets)
