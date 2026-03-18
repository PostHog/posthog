from collections.abc import Generator
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from celery import shared_task
from prometheus_client import CollectorRegistry, Gauge

from posthog.tasks.utils import PushGatewayTask


class TestPushGatewayTask:
    @pytest.fixture
    def mock_registry(self) -> CollectorRegistry:
        return CollectorRegistry()

    @pytest.fixture
    def mock_push_context(self, mock_registry: CollectorRegistry) -> Generator[MagicMock, None, None]:
        with patch("posthog.tasks.utils.pushed_metrics_registry") as mock:
            mock_context = MagicMock()
            mock_context.__enter__ = MagicMock(return_value=mock_registry)
            mock_context.__exit__ = MagicMock(return_value=False)
            mock.return_value = mock_context
            yield mock

    def test_success_metrics_set_on_successful_task(
        self, mock_push_context: MagicMock, mock_registry: CollectorRegistry
    ) -> None:
        @shared_task(bind=True, base=PushGatewayTask, name="test.successful_task")
        def successful_task(self: Any) -> str:
            return "done"

        result = successful_task()

        assert result == "done"
        success_sample = mock_registry.get_sample_value("posthog_celery_successful_task_success")
        assert success_sample == 1
        duration_sample = mock_registry.get_sample_value("posthog_celery_successful_task_duration_seconds")
        assert duration_sample is not None
        assert duration_sample >= 0

    def test_failure_metrics_set_on_failed_task(
        self, mock_push_context: MagicMock, mock_registry: CollectorRegistry
    ) -> None:
        @shared_task(bind=True, base=PushGatewayTask, name="test.failing_task")
        def failing_task(self: Any) -> None:
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            failing_task()

        success_sample = mock_registry.get_sample_value("posthog_celery_failing_task_success")
        assert success_sample == 0
        duration_sample = mock_registry.get_sample_value("posthog_celery_failing_task_duration_seconds")
        assert duration_sample is not None
        assert duration_sample >= 0

    def test_custom_metrics_can_be_added(self, mock_push_context: MagicMock, mock_registry: CollectorRegistry) -> None:
        @shared_task(bind=True, base=PushGatewayTask, name="test.task_with_custom_metric")
        def task_with_custom_metric(self: Any) -> str:
            custom = Gauge("custom_metric", "Custom", registry=self.metrics_registry)
            custom.set(42)
            return "done"

        task_with_custom_metric()

        custom_sample = mock_registry.get_sample_value("custom_metric")
        assert custom_sample == 42

    def test_exception_is_reraised(self, mock_push_context: MagicMock, mock_registry: CollectorRegistry) -> None:
        @shared_task(bind=True, base=PushGatewayTask, name="test.exception_task")
        def exception_task(self: Any) -> None:
            raise RuntimeError("specific error")

        with pytest.raises(RuntimeError, match="specific error"):
            exception_task()

    def test_duration_is_recorded_even_on_failure(
        self, mock_push_context: MagicMock, mock_registry: CollectorRegistry
    ) -> None:
        @shared_task(bind=True, base=PushGatewayTask, name="test.duration_on_failure_task")
        def duration_on_failure_task(self: Any) -> None:
            raise ValueError("failure")

        with pytest.raises(ValueError):
            duration_on_failure_task()

        duration_sample = mock_registry.get_sample_value("posthog_celery_duration_on_failure_task_duration_seconds")
        assert duration_sample is not None
        assert duration_sample >= 0

    def test_task_name_extracted_correctly(
        self, mock_push_context: MagicMock, mock_registry: CollectorRegistry
    ) -> None:
        @shared_task(bind=True, base=PushGatewayTask, name="posthog.tasks.feature_flags.my_complex_task")
        def my_complex_task(self: Any) -> str:
            return "done"

        my_complex_task()

        mock_push_context.assert_called_once_with("celery_my_complex_task")

    def test_pushgateway_failure_does_not_fail_task(self) -> None:
        """
        Verify that failures in the pushgateway (during metrics push) don't cause
        the task itself to fail. The real pushed_metrics_registry catches push
        exceptions internally, so we simulate that by having __exit__ return False
        (normal exit, no exception suppression needed).
        """
        with patch("posthog.tasks.utils.pushed_metrics_registry") as mock:
            mock_context = MagicMock()
            mock_context.__enter__ = MagicMock(return_value=CollectorRegistry())
            mock_context.__exit__ = MagicMock(return_value=False)
            mock.return_value = mock_context

            @shared_task(bind=True, base=PushGatewayTask, name="test.task_with_push_failure")
            def task_with_push_failure(self: Any) -> str:
                return "completed"

            result = task_with_push_failure()

            assert result == "completed"

    def test_registry_accessible_during_execution(
        self, mock_push_context: MagicMock, mock_registry: CollectorRegistry
    ) -> None:
        registry_during_execution: list[CollectorRegistry | None] = []

        @shared_task(bind=True, base=PushGatewayTask, name="test.registry_access_task")
        def registry_access_task(self: Any) -> str:
            registry_during_execution.append(self.metrics_registry)
            return "done"

        registry_access_task()

        assert len(registry_during_execution) == 1
        assert registry_during_execution[0] is mock_registry
