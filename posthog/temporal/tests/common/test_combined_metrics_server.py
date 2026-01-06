import socket
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from prometheus_client import CollectorRegistry, Counter

from posthog.temporal.common.combined_metrics_server import CombinedMetricsServer
from posthog.temporal.common.worker import get_free_port


def create_mock_temporal_server(port: int, metrics_content: bytes) -> HTTPServer:
    """Create a mock HTTP server that returns the given metrics content."""

    class MockHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(metrics_content)

        def log_message(self, format: str, *args: object) -> None:
            pass  # Suppress logging

    server = HTTPServer(("127.0.0.1", port), MockHandler)
    return server


@pytest.fixture
def isolated_registry():
    """Create an isolated CollectorRegistry for test isolation."""
    return CollectorRegistry()


@pytest.fixture
def test_counter(isolated_registry):
    """Create a test prometheus_client counter in an isolated registry."""
    counter_name = "test_counter"
    counter = Counter(counter_name, "A test counter for combined metrics", registry=isolated_registry)
    counter.inc()
    return counter_name


class TestCombinedMetricsServer:
    def test_serves_combined_metrics(self, test_counter, isolated_registry):
        temporal_port = get_free_port()
        metrics_port = get_free_port()

        # Mock Temporal metrics
        temporal_metrics = b"""# HELP temporal_workflow_completed Workflow completions
# TYPE temporal_workflow_completed counter
temporal_workflow_completed{namespace="default"} 42
# HELP temporal_request Count of client request successes by rpc name
# TYPE temporal_request counter
temporal_request{operation="GetSystemInfo",service_name="temporal-core-sdk"} 1
temporal_request{namespace="default",operation="DescribeNamespace",service_name="temporal-core-sdk"} 1
# HELP temporal_long_request_latency Histogram of client long-poll request latencies
# TYPE temporal_long_request_latency histogram
temporal_long_request_latency_bucket{namespace="default",operation="PollActivityTaskQueue",service_name="temporal-core-sdk",task_queue="development-task-queue",le="50"} 8
temporal_long_request_latency_bucket{namespace="default",operation="PollActivityTaskQueue",service_name="temporal-core-sdk",task_queue="development-task-queue",le="100"} 8
temporal_long_request_latency_bucket{namespace="default",operation="PollActivityTaskQueue",service_name="temporal-core-sdk",task_queue="development-task-queue",le="500"} 8
temporal_long_request_latency_bucket{namespace="default",operation="PollActivityTaskQueue",service_name="temporal-core-sdk",task_queue="development-task-queue",le="1000"} 8
temporal_long_request_latency_bucket{namespace="default",operation="PollActivityTaskQueue",service_name="temporal-core-sdk",task_queue="development-task-queue",le="2500"} 8
temporal_long_request_latency_bucket{namespace="default",operation="PollActivityTaskQueue",service_name="temporal-core-sdk",task_queue="development-task-queue",le="10000"} 8
temporal_long_request_latency_bucket{namespace="default",operation="PollActivityTaskQueue",service_name="temporal-core-sdk",task_queue="development-task-queue",le="+Inf"} 313
"""

        mock_server = create_mock_temporal_server(temporal_port, temporal_metrics)
        mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
        mock_thread.start()

        server = CombinedMetricsServer(
            port=metrics_port,
            temporal_metrics_url=f"http://127.0.0.1:{temporal_port}/metrics",
            registry=isolated_registry,
        )
        server.start()

        try:
            url = f"http://127.0.0.1:{metrics_port}/metrics"
            with urllib.request.urlopen(url, timeout=5) as response:
                content = response.read().decode("utf-8")

            # Check Temporal metrics are included
            assert temporal_metrics.decode() in content
            # Check prometheus_client metrics are included
            assert test_counter in content
        finally:
            server.stop()
            mock_server.shutdown()

    def test_serves_metrics_when_temporal_unavailable(self, test_counter, isolated_registry):
        temporal_port = get_free_port()  # No server running on this port
        metrics_port = get_free_port()

        server = CombinedMetricsServer(
            port=metrics_port,
            temporal_metrics_url=f"http://127.0.0.1:{temporal_port}/metrics",
            registry=isolated_registry,
        )
        server.start()

        try:
            url = f"http://127.0.0.1:{metrics_port}/metrics"
            with urllib.request.urlopen(url, timeout=5) as response:
                content = response.read().decode("utf-8")

            # prometheus_client metrics should still be served
            assert test_counter in content
            assert "temporal" not in content
        finally:
            server.stop()

    def test_returns_404_for_unknown_paths(self, isolated_registry):
        temporal_port = get_free_port()
        metrics_port = get_free_port()

        server = CombinedMetricsServer(
            port=metrics_port,
            temporal_metrics_url=f"http://127.0.0.1:{temporal_port}/metrics",
            registry=isolated_registry,
        )
        server.start()

        try:
            url = f"http://127.0.0.1:{metrics_port}/unknown"
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(url, timeout=5)

            assert exc_info.value.code == 404
        finally:
            server.stop()

    def test_root_path_serves_metrics(self, test_counter, isolated_registry):
        temporal_port = get_free_port()
        metrics_port = get_free_port()

        temporal_metrics = b"""# HELP temporal_active_workers Active workers
# TYPE temporal_active_workers gauge
temporal_active_workers{task_queue="main"} 5
"""

        mock_server = create_mock_temporal_server(temporal_port, temporal_metrics)
        mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
        mock_thread.start()

        server = CombinedMetricsServer(
            port=metrics_port,
            temporal_metrics_url=f"http://127.0.0.1:{temporal_port}/metrics",
            registry=isolated_registry,
        )
        server.start()

        try:
            url = f"http://127.0.0.1:{metrics_port}/"
            with urllib.request.urlopen(url, timeout=5) as response:
                content = response.read().decode("utf-8")

            assert temporal_metrics.decode() in content
            assert test_counter in content
        finally:
            server.stop()
            mock_server.shutdown()

    def test_counter_metrics_preserve_type_without_total_suffix(self, isolated_registry):
        """Verify that Temporal counter metrics preserve their format when passed through."""
        temporal_port = get_free_port()
        metrics_port = get_free_port()

        # This is the format Temporal produces with counters_total_suffix=False
        # This is different compared to Pythons Prometheus Client which always adds the _total suffix.
        temporal_metrics = b"""# HELP temporal_request Count of requests
# TYPE temporal_request counter
temporal_request{operation="GetSystemInfo"} 1
temporal_request{operation="DescribeNamespace"} 2
"""

        mock_server = create_mock_temporal_server(temporal_port, temporal_metrics)
        mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
        mock_thread.start()

        server = CombinedMetricsServer(
            port=metrics_port,
            temporal_metrics_url=f"http://127.0.0.1:{temporal_port}/metrics",
            registry=isolated_registry,
        )
        server.start()

        try:
            url = f"http://127.0.0.1:{metrics_port}/metrics"
            with urllib.request.urlopen(url, timeout=5) as response:
                content = response.read().decode("utf-8")

            # Verify counter type is preserved
            assert "# TYPE temporal_request counter" in content
            # Verify metric name has no _total suffix
            assert "temporal_request{" in content
            assert "temporal_request_total" not in content
        finally:
            server.stop()
            mock_server.shutdown()


class TestGetFreePort:
    def test_returns_available_port(self):
        port = get_free_port()
        assert isinstance(port, int)
        assert port > 0

        # Verify the port is actually available
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
