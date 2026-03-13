from unittest.mock import MagicMock, patch

from prometheus_client import CollectorRegistry


class PushGatewayTaskTestMixin:
    """Sets up mocked PushGateway context so PushGatewayTask-based tasks can run in tests."""

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        self.registry = CollectorRegistry()
        self.mock_context = MagicMock()
        self.mock_context.__enter__ = MagicMock(return_value=self.registry)
        self.mock_context.__exit__ = MagicMock(return_value=False)
        self.patcher = patch("posthog.tasks.utils.pushed_metrics_registry", return_value=self.mock_context)
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        super().tearDown()  # type: ignore[misc]
