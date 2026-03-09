import pytest

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


def test_is_task_queue_supported_raises_without_task_queue():
    class NoQueueInterceptor(Interceptor):
        pass

    with pytest.raises(ValueError):
        is_task_queue_supported("any-queue", NoQueueInterceptor)
