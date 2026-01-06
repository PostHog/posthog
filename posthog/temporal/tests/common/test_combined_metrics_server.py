import socket
import urllib.error
import urllib.request

import pytest
from unittest.mock import MagicMock

from prometheus_client import CollectorRegistry, Counter
from temporalio.runtime import (
    BUFFERED_METRIC_KIND_COUNTER,
    BUFFERED_METRIC_KIND_GAUGE,
    BUFFERED_METRIC_KIND_HISTOGRAM,
    MetricBuffer,
)

from posthog.temporal.common.combined_metrics_server import (
    DEFAULT_HISTOGRAM_BUCKETS,
    CombinedMetricsServer,
    TemporalMetricsCollector,
)


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
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
def isolated_registry():
    """Create an isolated CollectorRegistry for test isolation."""
    return CollectorRegistry()


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
def test_counter(isolated_registry):
    """Create a test prometheus_client counter in an isolated registry."""
    counter_name = "test_counter"
    counter = Counter(counter_name, "A test counter for combined metrics", registry=isolated_registry)
    counter.inc()
    return counter_name


class TestTemporalMetricsCollector:
    def test_collects_counter_metrics(self, isolated_registry):
        buffer = MagicMock(spec=MetricBuffer)
        buffer.retrieve_updates.return_value = [
            create_mock_metric_update("counter", BUFFERED_METRIC_KIND_COUNTER, 10, {"label": "value"}),
        ]

        collector = TemporalMetricsCollector(buffer, metric_prefix="test_", registry=isolated_registry)
        collector.collect_updates()

        assert "test_counter:label" in collector._metrics
        metric = collector._metrics["test_counter:label"]
        assert metric._name == "test_counter"

    def test_collects_gauge_metrics(self, isolated_registry):
        buffer = MagicMock(spec=MetricBuffer)
        buffer.retrieve_updates.return_value = [
            create_mock_metric_update("gauge", BUFFERED_METRIC_KIND_GAUGE, 25.5, {"host": "worker1"}),
        ]

        collector = TemporalMetricsCollector(buffer, metric_prefix="test_", registry=isolated_registry)
        collector.collect_updates()

        assert "test_gauge:host" in collector._metrics

    def test_collects_histogram_metrics(self, isolated_registry):
        buffer = MagicMock(spec=MetricBuffer)
        buffer.retrieve_updates.return_value = [
            create_mock_metric_update("histogram", BUFFERED_METRIC_KIND_HISTOGRAM, 150.0, {}),
        ]

        collector = TemporalMetricsCollector(buffer, metric_prefix="test_", registry=isolated_registry)
        collector.collect_updates()

        assert "test_histogram:" in collector._metrics

    def test_handles_empty_buffer(self, isolated_registry):
        buffer = MagicMock(spec=MetricBuffer)
        buffer.retrieve_updates.return_value = []

        collector = TemporalMetricsCollector(buffer, metric_prefix="test_", registry=isolated_registry)
        collector.collect_updates()

        assert len(collector._metrics) == 0

    def test_handles_buffer_error(self, isolated_registry):
        buffer = MagicMock(spec=MetricBuffer)
        buffer.retrieve_updates.side_effect = RuntimeError("Buffer error")

        collector = TemporalMetricsCollector(buffer, metric_prefix="test_", registry=isolated_registry)
        collector.collect_updates()

        assert len(collector._metrics) == 0

    def test_accumulates_counter_increments(self, isolated_registry):
        buffer = MagicMock(spec=MetricBuffer)
        buffer.retrieve_updates.return_value = [
            create_mock_metric_update("accumulated", BUFFERED_METRIC_KIND_COUNTER, 5, {}),
        ]

        collector = TemporalMetricsCollector(buffer, metric_prefix="test_", registry=isolated_registry)
        collector.collect_updates()

        buffer.retrieve_updates.return_value = [
            create_mock_metric_update("accumulated", BUFFERED_METRIC_KIND_COUNTER, 3, {}),
        ]
        collector.collect_updates()

        metric = collector._metrics["test_accumulated:"]
        # Counter should have been incremented twice (5 + 3 = 8)
        assert metric._value.get() == 8.0  # type: ignore[union-attr]

    def test_skips_updates_with_mismatched_label_sets(self, isolated_registry):
        buffer = MagicMock(spec=MetricBuffer)
        buffer.retrieve_updates.return_value = [
            create_mock_metric_update("my_metric", BUFFERED_METRIC_KIND_COUNTER, 10, {"label_a": "value"}),
        ]

        collector = TemporalMetricsCollector(buffer, metric_prefix="test_", registry=isolated_registry)
        collector.collect_updates()

        buffer.retrieve_updates.return_value = [
            create_mock_metric_update("my_metric", BUFFERED_METRIC_KIND_COUNTER, 5, {"label_b": "value"}),
        ]
        collector.collect_updates()

        assert len(collector._metrics) == 1
        assert "test_my_metric:label_a" in collector._metrics


class TestCombinedMetricsServer:
    def test_serves_combined_metrics(self, mock_metric_buffer, test_counter, isolated_registry):
        port = get_free_port()

        server = CombinedMetricsServer(
            port=port,
            metric_buffer=mock_metric_buffer,
            metric_prefix="test_",
            registry=isolated_registry,
        )
        server.start()

        try:
            url = f"http://127.0.0.1:{port}/metrics"
            with urllib.request.urlopen(url, timeout=5) as response:
                content = response.read().decode("utf-8")

            # Check Temporal metrics from buffer (with prefix)
            assert "test_workflow_completed" in content
            assert "test_active_workers" in content
            # Check prometheus_client metrics
            assert test_counter in content
        finally:
            server.stop()

    def test_serves_metrics_when_buffer_empty(self, test_counter, isolated_registry):
        port = get_free_port()
        empty_buffer = MagicMock(spec=MetricBuffer)
        empty_buffer.retrieve_updates.return_value = []

        server = CombinedMetricsServer(
            port=port,
            metric_buffer=empty_buffer,
            metric_prefix="empty_",
            registry=isolated_registry,
        )
        server.start()

        try:
            url = f"http://127.0.0.1:{port}/metrics"
            with urllib.request.urlopen(url, timeout=5) as response:
                content = response.read().decode("utf-8")

            # No Temporal metrics with our prefix since buffer is empty
            assert "empty_" not in content
            # But prometheus_client metrics should still be there
            assert test_counter in content
        finally:
            server.stop()

    def test_returns_404_for_unknown_paths(self, mock_metric_buffer, isolated_registry):
        port = get_free_port()

        server = CombinedMetricsServer(
            port=port,
            metric_buffer=mock_metric_buffer,
            metric_prefix="test_",
            registry=isolated_registry,
        )
        server.start()

        try:
            url = f"http://127.0.0.1:{port}/unknown"
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(url, timeout=5)

            assert exc_info.value.code == 404
        finally:
            server.stop()

    def test_root_path_serves_metrics(self, mock_metric_buffer, test_counter, isolated_registry):
        port = get_free_port()

        server = CombinedMetricsServer(
            port=port,
            metric_buffer=mock_metric_buffer,
            metric_prefix="test_",
            registry=isolated_registry,
        )
        server.start()

        try:
            url = f"http://127.0.0.1:{port}/"
            with urllib.request.urlopen(url, timeout=5) as response:
                content = response.read().decode("utf-8")

            assert "test_workflow_completed" in content
            assert test_counter in content
        finally:
            server.stop()


class TestDefaultHistogramBuckets:
    def test_buckets_cover_wide_range(self):
        assert DEFAULT_HISTOGRAM_BUCKETS[0] == 1.0  # 1ms
        assert DEFAULT_HISTOGRAM_BUCKETS[-1] == float("inf")
        assert 3600000.0 in DEFAULT_HISTOGRAM_BUCKETS  # 1 hour in ms
        assert 21600000.0 in DEFAULT_HISTOGRAM_BUCKETS  # 6 hours in ms
        assert 43200000.0 in DEFAULT_HISTOGRAM_BUCKETS  # 12 hours in ms
        assert 86400000.0 in DEFAULT_HISTOGRAM_BUCKETS  # 24 hours in ms

    def test_buckets_are_sorted(self):
        finite_buckets = [b for b in DEFAULT_HISTOGRAM_BUCKETS if b != float("inf")]
        assert finite_buckets == sorted(finite_buckets)


class TestHistogramBucketOverrides:
    def test_uses_custom_buckets_for_specified_metric(self, isolated_registry):
        buffer = MagicMock(spec=MetricBuffer)
        buffer.retrieve_updates.return_value = [
            create_mock_metric_update("custom_histogram", BUFFERED_METRIC_KIND_HISTOGRAM, 3.0, {}),
        ]

        custom_buckets = (1.0, 5.0, 10.0, float("inf"))
        collector = TemporalMetricsCollector(
            buffer,
            metric_prefix="test_",
            histogram_bucket_overrides={"custom_histogram": custom_buckets},
            registry=isolated_registry,
        )
        collector.collect_updates()

        metric = collector._metrics["test_custom_histogram:"]
        assert tuple(metric._upper_bounds) == custom_buckets  # type: ignore[union-attr]

    def test_uses_default_buckets_for_unspecified_metric(self, isolated_registry):
        buffer = MagicMock(spec=MetricBuffer)
        buffer.retrieve_updates.return_value = [
            create_mock_metric_update("default_histogram", BUFFERED_METRIC_KIND_HISTOGRAM, 100.0, {}),
        ]

        collector = TemporalMetricsCollector(
            buffer,
            metric_prefix="test_",
            histogram_bucket_overrides={"other_metric": (1.0, 2.0, float("inf"))},
            registry=isolated_registry,
        )
        collector.collect_updates()

        metric = collector._metrics["test_default_histogram:"]
        assert tuple(metric._upper_bounds) == DEFAULT_HISTOGRAM_BUCKETS  # type: ignore[union-attr]
