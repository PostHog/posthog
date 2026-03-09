import typing

from temporalio.worker import Interceptor


class AllTaskQueues:
    """Sentinel type indicating all task queues are supported."""

    pass


ALL_TASK_QUEUES = AllTaskQueues()


class _HasTaskQueue(typing.Protocol):
    """Protocol for interceptors to indicate which task queue(s) they support."""

    task_queue: typing.ClassVar[str | tuple[str, ...] | AllTaskQueues]


def _is_has_task_queue(interceptor: Interceptor | type[Interceptor]) -> typing.TypeGuard[_HasTaskQueue]:
    return hasattr(interceptor, "task_queue")


def is_task_queue_supported(
    task_queue: str,
    interceptor: Interceptor | type[Interceptor],
) -> bool:
    """Return whether the ``task_queue`` is supported by ``interceptor``."""
    # TODO: Should support also checking activities and workflows.
    # For when the queue is shared among many products.
    if not _is_has_task_queue(interceptor):
        raise ValueError("Interceptor does not have a defined task queue")

    match interceptor.task_queue:
        case AllTaskQueues():
            return True
        case tuple():
            return task_queue in interceptor.task_queue
        case str():
            return task_queue == interceptor.task_queue
        case _ as unreachable:
            typing.assert_never(unreachable)
