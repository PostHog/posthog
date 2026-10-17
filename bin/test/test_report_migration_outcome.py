import os
import sys
import threading
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import unittest

PUBLISHER = Path(__file__).resolve().parents[1] / "report-migration-outcome"


class TestMigrationOutcomePublisher(unittest.TestCase):
    def test_pushgateway_request_bypasses_egress_proxy(self) -> None:
        pushes: list[tuple[str, str]] = []
        proxy_requests: list[str] = []

        class Gateway(BaseHTTPRequestHandler):
            def do_PUT(self) -> None:
                pushes.append((self.path, self.rfile.read(int(self.headers["Content-Length"])).decode()))
                self.send_response(202)
                self.end_headers()

            def log_message(self, *args: object) -> None:
                pass

        class Proxy(BaseHTTPRequestHandler):
            def do_PUT(self) -> None:
                proxy_requests.append(self.path)
                self.send_error(407, "Deny: Private Range")

            def log_message(self, *args: object) -> None:
                pass

        with (
            ThreadingHTTPServer(("127.0.0.1", 0), Gateway) as gateway,
            ThreadingHTTPServer(("127.0.0.1", 0), Proxy) as proxy,
        ):
            threads = [threading.Thread(target=server.serve_forever) for server in (gateway, proxy)]
            for thread in threads:
                thread.start()
            try:
                env = {key: value for key, value in os.environ.items() if not key.lower().endswith("_proxy")}
                env.pop("REQUEST_METHOD", None)
                env.update(
                    HTTP_PROXY=f"http://127.0.0.1:{proxy.server_port}",
                    NO_PROXY="pyroscope-distributor.pyroscope.svc,sts.us-east-1.amazonaws.com",
                    PROM_PUSHGATEWAY_ADDRESS=f"127.0.0.1:{gateway.server_port}",
                    MIGRATION_JOB_NAME="migration-sync-test",
                    MIGRATION_NAMESPACE="posthog-web-django",
                )
                result = subprocess.run(
                    [sys.executable, str(PUBLISHER), "clickhouse"],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=True,
                )
            finally:
                for server in (gateway, proxy):
                    server.shutdown()
                for thread in threads:
                    thread.join()

        self.assertEqual(result.stderr, "")
        self.assertEqual(proxy_requests, [])
        self.assertEqual(len(pushes), 1)
        path, body = pushes[0]
        self.assertEqual(path, "/metrics/job/django_migrate_outcome/instance/posthog")
        self.assertIn('job_name="migration-sync-test"', body)
        self.assertIn('phase="clickhouse"', body)
        self.assertIn("django_migration_outcome{", body)
        self.assertIn("} 1.0", body)
