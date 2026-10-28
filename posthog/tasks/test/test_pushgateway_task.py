from collections.abc import Generator

import pytest
from unittest.mock import MagicMock, patch

from celery import shared_task
from celery.exceptions import Ignore, Reject, Retry, SoftTimeLimitExceeded
from prometheus_client import CollectorRegistry, Gauge
from pytest_django import Settings

from posthog.tasks.utils import FAILURE_PUSH_TIMEOUT_SECONDS, PushGatewayTask

TASK_GAUGE = "sample_task_rows_processed"


# Celery keeps the first task registered under a name. A second definition with the same name runs the first body.
# The cases pass the error to one task as an argument instead of defining a task for each case.
@shared_task(bind=True, base=PushGatewayTask, name="test.pushgateway.sample_task")
def sample_task(self: PushGatewayTask, error: Exception | None = None) -> str:
    Gauge(TASK_GAUGE, "Rows the task processed", registry=self.metrics_registry).set(42)
    if error is not None:
        raise error
    return "done"


def _pushed_registry(push: MagicMock) -> CollectorRegistry:
    push.assert_called_once()
    assert push.call_args.kwargs["job"] == "celery_sample_task"
    registry = push.call_args.kwargs["registry"]
    assert isinstance(registry, CollectorRegistry)
    return registry


class TestPushGatewayTask:
    @pytest.fixture(autouse=True)
    def pushgateway_address(self, settings: Settings) -> None:
        settings.PROM_PUSHGATEWAY_ADDRESS = "http://pushgateway.example.com:9091"

    @pytest.fixture
    def push_to_gateway(self) -> Generator[MagicMock]:
        with patch("posthog.metrics.push_to_gateway") as mock:
            yield mock

    @pytest.fixture
    def pushadd_to_gateway(self) -> Generator[MagicMock]:
        with patch("posthog.metrics.pushadd_to_gateway") as mock:
            yield mock

    @pytest.fixture
    def run_duration(self) -> Generator[float]:
        with patch("posthog.tasks.utils.time") as mock_time:
            mock_time.monotonic.side_effect = [100.0, 107.5]
            yield 7.5

    def test_completed_run_puts_its_metrics_and_returns_despite_a_push_error(
        self, run_duration: float, push_to_gateway: MagicMock, pushadd_to_gateway: MagicMock
    ) -> None:
        push_to_gateway.side_effect = OSError("pushgateway unreachable")

        result = sample_task()

        assert result == "done"
        registry = _pushed_registry(push_to_gateway)
        assert registry.get_sample_value("posthog_celery_sample_task_success") == 1
        assert registry.get_sample_value("posthog_celery_sample_task_duration_seconds") == run_duration
        assert registry.get_sample_value(TASK_GAUGE) == 42
        pushadd_to_gateway.assert_not_called()

    @pytest.mark.parametrize(
        "error",
        [ValueError("boom"), SoftTimeLimitExceeded()],
        ids=["value_error", "soft_time_limit"],
    )
    def test_failed_run_posts_only_failure_and_duration_and_reraises_despite_a_push_error(
        self, error: Exception, run_duration: float, push_to_gateway: MagicMock, pushadd_to_gateway: MagicMock
    ) -> None:
        pushadd_to_gateway.side_effect = OSError("pushgateway unreachable")

        with pytest.raises(type(error)) as exc_info:
            sample_task(error)

        assert exc_info.value is error
        registry = _pushed_registry(pushadd_to_gateway)
        assert pushadd_to_gateway.call_args.kwargs["timeout"] == FAILURE_PUSH_TIMEOUT_SECONDS
        assert registry.get_sample_value("posthog_celery_sample_task_success") == 0
        assert registry.get_sample_value("posthog_celery_sample_task_duration_seconds") == run_duration
        assert registry.get_sample_value(TASK_GAUGE) is None
        push_to_gateway.assert_not_called()

    @pytest.mark.parametrize(
        "predicate",
        [Retry(), Ignore(), Reject("reason", requeue=False)],
        ids=["retry", "ignore", "reject"],
    )
    def test_task_predicate_is_reraised_and_pushes_nothing(
        self, predicate: Exception, push_to_gateway: MagicMock, pushadd_to_gateway: MagicMock
    ) -> None:
        with pytest.raises(type(predicate)) as exc_info:
            sample_task(predicate)

        assert exc_info.value is predicate
        push_to_gateway.assert_not_called()
        pushadd_to_gateway.assert_not_called()
