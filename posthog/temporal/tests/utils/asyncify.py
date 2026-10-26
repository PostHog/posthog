from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Protocol

from posthog.temporal.common import utils
from posthog.temporal.common.utils import configure_asyncify_executor, get_asyncify_executor


class ConfigureExecutor(Protocol):
    def __call__(self, max_workers: int) -> ThreadPoolExecutor: ...


@contextmanager
def restored_asyncify_executor() -> Iterator[ConfigureExecutor]:
    """Let a test configure the worker's asyncify pool, then put back whatever pool was set before."""
    previous = get_asyncify_executor()
    try:
        yield configure_asyncify_executor
    finally:
        configured = get_asyncify_executor()
        if configured is not previous and configured is not None:
            configured.shutdown(wait=False)
        utils._asyncify_executor = previous
