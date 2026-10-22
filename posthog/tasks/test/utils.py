from collections.abc import Iterator
from contextlib import contextmanager

from unittest.mock import patch

from prometheus_client import CollectorRegistry


class PushGatewayTaskTestMixin:
    """Sets up mocked PushGateway context so PushGatewayTask-based tasks can run in tests.

    Each task run gets a fresh registry, as in production. `self.registry` holds the registry of the latest run.
    """

    registry: CollectorRegistry

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        self.patcher = patch("posthog.tasks.utils.pushed_metrics_registry", self._pushed_metrics_registry)
        self.patcher.start()

    @contextmanager
    def _pushed_metrics_registry(self, _job_name: str) -> Iterator[CollectorRegistry]:
        self.registry = CollectorRegistry()
        yield self.registry

    def tearDown(self) -> None:
        self.patcher.stop()
        super().tearDown()  # type: ignore[misc]
