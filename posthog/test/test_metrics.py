import threading
import http.server

import prometheus_client.exposition as expo
from prometheus_client import REGISTRY, CollectorRegistry, Gauge, push_to_gateway

from posthog.metrics import _make_handler_no_proxy, pushed_metrics_registry


class TestPushgatewayProxyPatch:
    def test_make_handler_is_patched(self):
        assert expo._make_handler is _make_handler_no_proxy

    def test_push_to_gateway_bypasses_proxy(self, monkeypatch):
        monkeypatch.setenv("HTTP_PROXY", "http://bogus-proxy:9999")
        monkeypatch.setenv("HTTPS_PROXY", "http://bogus-proxy:9999")

        received: dict = {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_PUT(self):
                received["path"] = self.path
                received["method"] = "PUT"
                received["content_type"] = self.headers.get("Content-Type")
                received["body"] = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self.send_response(200)
                self.end_headers()

            def log_message(self, format, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.handle_request)
        thread.start()

        try:
            registry = CollectorRegistry()
            g = Gauge("test_bypass_metric", "A test gauge", registry=registry)
            g.set(42.0)
            push_to_gateway(f"http://127.0.0.1:{port}", job="test_job", registry=registry)
        finally:
            thread.join(timeout=5)
            server.server_close()

        assert received["method"] == "PUT"
        assert "/metrics/job/test_job" in received["path"]
        body = received["body"].decode()
        assert "test_bypass_metric" in body
        assert "42.0" in body

    def test_pushed_metrics_registry_bypasses_proxy(self, monkeypatch, settings):
        monkeypatch.setenv("HTTP_PROXY", "http://bogus-proxy:9999")
        monkeypatch.setenv("HTTPS_PROXY", "http://bogus-proxy:9999")

        received: dict = {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_PUT(self):
                received["path"] = self.path
                received["body"] = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self.send_response(200)
                self.end_headers()

            def log_message(self, format, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.handle_request)
        thread.start()

        try:
            settings.PROM_PUSHGATEWAY_ADDRESS = f"http://127.0.0.1:{port}"
            with pushed_metrics_registry("ctx_job") as registry:
                g = Gauge("test_ctx_metric", "A context gauge", registry=registry)
                g.set(99.0)
        finally:
            thread.join(timeout=5)
            server.server_close()

        assert received, "HTTP server never received a request — push_to_gateway may have failed silently"
        assert "/metrics/job/ctx_job" in received["path"]
        body = received["body"].decode()
        assert "test_ctx_metric" in body
        assert "99.0" in body


class TestPushFailureClassification:
    @staticmethod
    def _failure_count(job: str, reason: str) -> float:
        return (
            REGISTRY.get_sample_value("posthog_pushgateway_push_failures_total", {"job": job, "reason": reason}) or 0.0
        )

    def test_unreachable_gateway_is_counted_and_not_captured(self, monkeypatch, settings):
        captured: list = []
        monkeypatch.setattr("posthog.metrics.capture_exception", captured.append)

        before = self._failure_count("unreachable_job", "unavailable")
        # Binding port 1 needs root, so nothing listens on it and the connection is refused at once.
        settings.PROM_PUSHGATEWAY_ADDRESS = "http://127.0.0.1:1"
        with pushed_metrics_registry("unreachable_job") as registry:
            Gauge("test_unreachable_metric", "A gauge nobody receives", registry=registry).set(1.0)

        assert captured == []
        assert self._failure_count("unreachable_job", "unavailable") == before + 1

    def test_rejected_push_is_counted_and_captured(self, monkeypatch, settings):
        captured: list = []
        monkeypatch.setattr("posthog.metrics.capture_exception", captured.append)

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_PUT(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self.send_response(500)
                self.end_headers()

            def log_message(self, format, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.handle_request)
        thread.start()

        before = self._failure_count("rejected_job", "error")
        try:
            settings.PROM_PUSHGATEWAY_ADDRESS = f"http://127.0.0.1:{port}"
            with pushed_metrics_registry("rejected_job") as registry:
                Gauge("test_rejected_metric", "A gauge the gateway refuses", registry=registry).set(1.0)
        finally:
            thread.join(timeout=5)
            server.server_close()

        assert len(captured) == 1
        assert self._failure_count("rejected_job", "error") == before + 1
