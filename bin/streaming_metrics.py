"""Prometheus metrics endpoint for the granian streaming server.

Granian workers write metrics into PROMETHEUS_MULTIPROC_DIR; this process
aggregates that directory and serves it on PROMETHEUS_METRICS_EXPORT_PORT,
mirroring what the Unit-based entrypoint exposes on the same port (there the
metrics app runs inside Unit itself, see unit.json.tpl). Run as a sidecar
process by bin/docker-server-streaming.
"""

import os
import time

from prometheus_client import CollectorRegistry, multiprocess, start_http_server


def main() -> None:
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    start_http_server(int(os.environ.get("PROMETHEUS_METRICS_EXPORT_PORT", "8001")), registry=registry)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
