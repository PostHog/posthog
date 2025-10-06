import asyncio
import threading
from collections.abc import AsyncGenerator, Callable, Generator
from queue import Queue
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def async_to_sync(async_handler: Callable[[], AsyncGenerator[Any, None]]) -> Generator[Any, None, None]:
    """Converts an async iterator to a sync generator."""

    q: Queue[Any] = Queue(maxsize=5000)
    sentinel = object()
    thread_exception = None

    async def runner():
        try:
            async for event in async_handler():
                q.put(event)
        except Exception as e:
            nonlocal thread_exception
            thread_exception = e
            q.put(sentinel)
        else:
            q.put(sentinel)

    def run_event_loop():
        asyncio.run(runner())

    # Use non-daemon thread with explicit cleanup
    thread = threading.Thread(target=run_event_loop, daemon=False)
    thread.start()

    try:
        # Yield items progressively as they arrive
        while True:
            item = q.get(timeout=60)  # Add timeout to prevent indefinite blocking. Matches max request TTL
            if item is sentinel:
                q.task_done()
                break

            yield item
            q.task_done()
    finally:
        # Ensure thread cleanup
        if thread.is_alive():
            # Signal thread to stop if possible, or wait briefly
            thread.join(timeout=1)
            if thread.is_alive():
                logger.warning("Thread did not terminate cleanly")

        if thread_exception:
            logger.error("Exception in async thread", exc_info=thread_exception)
