import pytest

from structlog.testing import capture_logs
from temporalio.worker import Interceptor

from posthog.temporal.common.interceptor import ALL_TASK_QUEUES, is_task_queue_supported


@pytest.mark.parametrize(
    "task_queue,interceptor_task_queue,supported",
    (
        ("test", "test", True),
        ("test", "not-test", False),
        ("test", ("not-test", "test"), True),
        ("test", ("not-test",), False),
        ("test", ALL_TASK_QUEUES, True),
        ("another", ALL_TASK_QUEUES, True),
    ),
)
def test_is_task_queue_supported(task_queue, interceptor_task_queue, supported):
    class MockInterceptor(Interceptor):
        task_queue = interceptor_task_queue

    result = is_task_queue_supported(task_queue, MockInterceptor)

    assert result is supported


def test_is_task_queue_supported_warns_without_task_queue():
    class NoQueueInterceptor(Interceptor):
        pass

    with capture_logs() as cap_logs:
        result = is_task_queue_supported("any-queue", NoQueueInterceptor)

    assert len(cap_logs) == 1
    record = cap_logs[0]

    assert record["log_level"] == "warning"
    assert "missing task queue" in record["event"]
    assert result is False
