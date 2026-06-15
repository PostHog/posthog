import threading
import http.server

import prometheus_client.exposition as expo
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

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
