import threading
import typing
from contextlib import contextmanager
from functools import partial

from celery import chain
from celery.canvas import Signature
from django.db import transaction

from posthog.schema import QueryStatus

if typing.TYPE_CHECKING:
    from posthog.clickhouse.client.execute_async import QueryStatusManager

# Create a thread-local storage for task chains
_thread_locals = threading.local()


def kick_off_task(
    manager: "QueryStatusManager",
    query_status: QueryStatus,
    task_signature: Signature,
) -> None:
    task = task_signature.apply_async()
    query_status.task_id = task.id
    manager.store_query_status(query_status)


def get_task_chain() -> list[tuple[Signature, "QueryStatusManager", QueryStatus]]:
    """
    Retrieves the task chain from thread-local storage.
    """
    if not hasattr(_thread_locals, "task_chain"):
        _thread_locals.task_chain = []
    return _thread_locals.task_chain


def set_in_context(value) -> None:
    """
    Sets the in_context flag in thread-local storage.
    """
    _thread_locals.in_context = value


def is_in_context() -> bool:
    """
    Checks if the in_context flag is set in thread-local storage.
    """
    return getattr(_thread_locals, "in_context", False)


def add_task_to_chain(task_signature: Signature, manager: "QueryStatusManager", query_status: QueryStatus) -> None:
    """
    Adds a task to the chain. If not in context, registers the task with on_commit directly.
    """

    if is_in_context():
        task_chain = get_task_chain()
        task_chain.append((task_signature, manager, query_status))
    else:
        transaction.on_commit(partial(kick_off_task, manager, query_status, task_signature))


def execute_task_chain() -> None:
    """
    Executes the task chain after the transaction is committed.
    """
    task_chain = get_task_chain()
    if task_chain:
        chained_tasks = chain(*[args[0] for args in task_chain])
        result = chained_tasks.apply_async()

        for args in task_chain:
            args[2].task_id = result.id
            args[1].store_query_status(args[2])

        _thread_locals.task_chain = []


@contextmanager
def task_chain_context() -> typing.Iterator[None]:
    set_in_context(True)
    try:
        yield
    finally:
        set_in_context(False)
        transaction.on_commit(execute_task_chain)
