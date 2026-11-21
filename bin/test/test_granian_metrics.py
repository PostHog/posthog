import os
import sys
import runpy
import select
import threading
import subprocess
import http.client
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

import unittest
from unittest.mock import patch

from parameterized import parameterized
from prometheus_client import CollectorRegistry, generate_latest, multiprocess

EXPORTER = Path(__file__).resolve().parents[1] / "granian_metrics.py"

WORKER = """
import sys
from prometheus_client import Counter, Gauge, Histogram

Gauge("reader_failed", "Reader failure", multiprocess_mode="livemax").set(int(sys.argv[1]))
Gauge("worker_peak", "Worker peak", multiprocess_mode="max").set(int(sys.argv[2]))
Counter("worker_reads", "Worker reads").inc(2)
Histogram("worker_duration_seconds", "Worker duration").observe(3)
print("ready", flush=True)
sys.stdin.read()
"""

SERVER = """
import runpy
import sys
from http.server import ThreadingHTTPServer

class ReadyServer(ThreadingHTTPServer):
    def server_activate(self) -> None:
        super().server_activate()
        print(self.server_port, flush=True)

main = runpy.run_path(sys.argv[1])["main"]
main.__globals__["ThreadingHTTPServer"] = ReadyServer
main()
"""


class TestGranianMetrics(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.env = {
            **os.environ,
            "PROMETHEUS_MULTIPROC_DIR": str(self.path),
            "PROMETHEUS_METRICS_EXPORT_PORT": "0",
            "GRANIAN_METRICS_ENABLED": "false",
            "GRANIAN_WORKERS": "2",
            "GRANIAN_RUNTIME_THREADS": "1",
        }
        self.exporter = runpy.run_path(str(EXPORTER))
        self.registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(self.registry, path=str(self.path))

    def stop_process(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream:
                stream.close()

    def start_process(self, script: str, *args: str) -> tuple[subprocess.Popen[str], str]:
        process = subprocess.Popen(
            [sys.executable, "-c", script, *args],
            env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(self.stop_process, process)
        assert process.stdout is not None
        self.assertTrue(select.select([process.stdout], [], [], 10)[0], "subprocess did not start")
        ready = process.stdout.readline().strip()
        if not ready:
            _, stderr = process.communicate(timeout=10)
            self.fail(f"subprocess exited before readiness: {stderr}")
        return process, ready

    def start_worker(self, failed: int, peak: int = 10) -> subprocess.Popen[str]:
        worker, ready = self.start_process(WORKER, str(failed), str(peak))
        self.assertEqual(ready, "ready")
        return worker

    def scrape(self, port: int) -> str:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            connection.request("GET", "/metrics")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            return response.read().decode()
        finally:
            connection.close()

    def test_scrapes_clear_dead_worker_failures_and_preserve_history(self) -> None:
        failed = self.start_worker(failed=1, peak=20)
        self.start_worker(failed=0)
        _, port_string = self.start_process(SERVER, str(EXPORTER))
        port = int(port_string)

        self.assertIn("reader_failed 1.0\n", self.scrape(port))
        failed.kill()
        failed.wait(timeout=10)

        body = self.scrape(port)
        self.assertIn("reader_failed 0.0\n", body)
        self.assertIn("worker_reads_total 4.0\n", body)
        self.assertIn("worker_duration_seconds_count 2.0\n", body)
        self.assertIn("worker_duration_seconds_sum 6.0\n", body)
        self.assertIn("worker_peak 20.0\n", body)
        self.assertIn("granian_workers_total 2.0\n", body)
        self.assertFalse((self.path / f"gauge_livemax_{failed.pid}.db").exists())
        self.assertTrue((self.path / f"counter_{failed.pid}.db").exists())

    @parameterized.expand([("alive", None), ("permission_denied", PermissionError()), ("unknown", OSError())])
    def test_keeps_gauges_unless_worker_is_confirmed_dead(self, _name: str, error: OSError | None) -> None:
        self.start_worker(failed=1)
        files = set(self.path.iterdir())

        with patch.object(self.exporter["os"], "kill", side_effect=error):
            self.exporter["cleanup_dead_worker_gauges"](self.path)

        self.assertEqual(set(self.path.iterdir()), files)
        self.assertIn(b"reader_failed 1.0\n", generate_latest(self.registry))

    def test_concurrent_cleanup_tolerates_another_scrape_removing_the_same_gauge(self) -> None:
        worker = self.start_worker(failed=1)
        worker.kill()
        worker.wait(timeout=10)
        barrier = threading.Barrier(2)
        deleted = threading.Event()
        remove = os.remove

        def concurrent_remove(path: str) -> None:
            if barrier.wait(timeout=10) == 0:
                remove(path)
                deleted.set()
            else:
                self.assertTrue(deleted.wait(timeout=10))
                remove(path)

        with patch.object(multiprocess.os, "remove", side_effect=concurrent_remove):
            with ThreadPoolExecutor(max_workers=2) as executor:
                list(executor.map(self.exporter["cleanup_dead_worker_gauges"], [self.path, self.path]))

        body = generate_latest(self.registry)
        self.assertNotIn(b"reader_failed", body)
        self.assertIn(b"worker_reads_total 2.0\n", body)


if __name__ == "__main__":
    unittest.main()
