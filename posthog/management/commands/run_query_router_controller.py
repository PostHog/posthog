import signal
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

from prometheus_client import start_http_server

from posthog.clickhouse.query_router.controller import ControllerLoop, LimitController, LoadReader

# The chart's liveness probe restarts the pod when this file is older than a minute, so the chart must use
# the same path.
HEARTBEAT_PATH = Path("/tmp/query-router-controller-heartbeat")


class Command(BaseCommand):
    help = "Run the query router controller, which sets each ClickHouse pool's query limit from node load"

    def handle(self, *args: Any, **options: Any) -> None:
        start_http_server(int(settings.PROMETHEUS_METRICS_EXPORT_PORT))
        loop = ControllerLoop(LimitController(load_reader=LoadReader()), heartbeat=HEARTBEAT_PATH.touch)
        # The process runs as PID 1 in its pod, and PID 1 ignores SIGTERM that has no handler. Stopping the
        # loop also releases the leader lease, so the other replica takes over on its next tick.
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda _signum, _frame: loop.stop())
        loop.run()
