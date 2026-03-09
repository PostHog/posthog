import typing


class AllTaskQueues:
    """Sentinel type indicating all task queues are supported."""

    pass


ALL_TASK_QUEUES = AllTaskQueues()


class _HasTaskQueue(typing.Protocol):
    """Protocol for interceptors to indicate which task queue(s) they support."""

    task_queue: typing.ClassVar[str | tuple[str, ...] | AllTaskQueues]


def is_task_queue_supported(
    task_queue: str,
    interceptor: _HasTaskQueue,
) -> bool:
    """Return whether the ``task_queue`` is supported by ``interceptor``."""
    # TODO: Should support also checking activities and workflows.
    # For when the queue is shared among many products.

    match interceptor.task_queue:
        case AllTaskQueues():
            return True
        case tuple():
            return task_queue in interceptor.task_queue
        case str():
            return task_queue == interceptor.task_queue
        case _ as unreachable:
            typing.assert_never(unreachable)
