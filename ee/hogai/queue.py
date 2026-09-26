from __future__ import annotations

import time
import asyncio
import builtins
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import Any, TypedDict, cast
from uuid import uuid4

from django.core.cache import caches
from django.utils import timezone

MAX_QUEUE_MESSAGES = 2
QUEUE_CACHE_TIMEOUT_SECONDS = 60 * 60


class ConversationQueueMessage(TypedDict):
    id: str
    content: str
    created_at: str
    contextual_tools: dict[str, Any] | None
    ui_context: dict[str, Any] | None
    billing_context: dict[str, Any] | None
    agent_mode: str | None
    session_id: str | None


class QueueFullError(Exception):
    pass


class QueueNotDrainableError(Exception):
    """No run will consume the queue, so a new message must be sent directly instead."""


@dataclass(frozen=False)
class ConversationQueueStore:
    conversation_id: str
    max_messages: int = MAX_QUEUE_MESSAGES
    cache_timeout_seconds: int = QUEUE_CACHE_TIMEOUT_SECONDS

    def _cache_key(self) -> str:
        return f"phai:max_conversation_queue_{self.conversation_id}"

    def _lock_key(self) -> str:
        return f"{self._cache_key()}_lock"

    def _drain_closed_key(self) -> str:
        return f"{self._cache_key()}_drain_closed"

    def _is_drain_closed(self) -> bool:
        return bool(caches["default"].get(self._drain_closed_key()))

    def _set_drain_closed(self, closed: bool) -> None:
        cache = caches["default"]
        if closed:
            cache.set(self._drain_closed_key(), True, timeout=self.cache_timeout_seconds)
        else:
            cache.delete(self._drain_closed_key())

    @contextmanager
    def _lock(self, timeout: float = 5.0):
        cache = caches["default"]
        lock_key = self._lock_key()
        start_time = time.monotonic()
        while not cache.add(lock_key, "1", timeout=timeout):
            if time.monotonic() - start_time > timeout:
                raise TimeoutError(f"Failed to acquire lock after {timeout}s")
            time.sleep(0.01)
        try:
            yield
        finally:
            cache.delete(lock_key)

    @asynccontextmanager
    async def _async_lock(self, timeout: float = 5.0):
        cache = caches["default"]
        lock_key = self._lock_key()
        start_time = time.monotonic()
        while not cache.add(lock_key, "1", timeout=timeout):
            if time.monotonic() - start_time > timeout:
                raise TimeoutError(f"Failed to acquire lock after {timeout}s")
            await asyncio.sleep(0.01)
        try:
            yield
        finally:
            cache.delete(lock_key)

    def list(self) -> builtins.list[ConversationQueueMessage]:
        cache = caches["default"]
        queue = cache.get(self._cache_key())
        if isinstance(queue, list):
            return cast(list[ConversationQueueMessage], queue)
        return []

    def save(self, queue_messages: builtins.list[ConversationQueueMessage]) -> None:
        cache = caches["default"]
        cache.set(self._cache_key(), queue_messages, timeout=self.cache_timeout_seconds)

    def clear(self) -> builtins.list[ConversationQueueMessage]:
        with self._lock():
            self.save([])
            return []

    async def clear_and_close_async(self) -> builtins.list[ConversationQueueMessage]:
        """Drop every queued message and close the drain, for a run that ends without draining."""
        async with self._async_lock():
            self.save([])
            self._set_drain_closed(True)
            return []

    def enqueue(self, message: ConversationQueueMessage) -> builtins.list[ConversationQueueMessage]:
        with self._lock():
            if self._is_drain_closed():
                raise QueueNotDrainableError
            queue = self.list()
            if len(queue) >= self.max_messages:
                raise QueueFullError
            queue.append(message)
            self.save(queue)
            return queue

    def update(self, queue_id: str, content: str) -> builtins.list[ConversationQueueMessage]:
        with self._lock():
            queue = self.list()
            for index, item in enumerate(queue):
                if item.get("id") == queue_id:
                    queue[index] = {**item, "content": content}
                    self.save(queue)
                    return queue
            return queue

    def delete(self, queue_id: str) -> builtins.list[ConversationQueueMessage]:
        with self._lock():
            queue = [item for item in self.list() if item.get("id") != queue_id]
            self.save(queue)
            return queue

    def _pop_next_locked(self) -> ConversationQueueMessage | None:
        queue = self.list()
        if not queue:
            return None
        message = queue.pop(0)
        self.save(queue)
        return message

    def pop_next(self) -> ConversationQueueMessage | None:
        with self._lock():
            return self._pop_next_locked()

    async def pop_next_or_close_async(self) -> ConversationQueueMessage | None:
        """Pop the next message, or close the drain when the queue is empty.

        The pop and the close share one lock, so a message that arrives after the last drain
        of a run is either popped by that run or refused at enqueue time. Without that,
        the message stays in the queue with no run left to consume it.
        """
        async with self._async_lock():
            message = self._pop_next_locked()
            if message is None:
                self._set_drain_closed(True)
            return message

    async def open_drain_async(self) -> None:
        """Let a new run accept follow-ups sent mid-turn, whatever the run before it left behind."""
        # One write to a key nothing else reads inside a lock, so the queue lock is not needed.
        self._set_drain_closed(False)

    def requeue_front(self, message: ConversationQueueMessage) -> builtins.list[ConversationQueueMessage]:
        with self._lock():
            queue = self.list()
            if len(queue) >= self.max_messages:
                queue = queue[: self.max_messages - 1]
            queue.insert(0, message)
            self.save(queue)
            return queue

    async def requeue_front_async(self, message: ConversationQueueMessage) -> builtins.list[ConversationQueueMessage]:
        async with self._async_lock():
            queue = self.list()
            if len(queue) >= self.max_messages:
                queue = queue[: self.max_messages - 1]
            queue.insert(0, message)
            self.save(queue)
            return queue


def build_queue_message(
    *,
    content: str,
    contextual_tools: dict[str, Any] | None = None,
    ui_context: dict[str, Any] | None = None,
    billing_context: dict[str, Any] | None = None,
    agent_mode: str | None = None,
    session_id: str | None = None,
) -> ConversationQueueMessage:
    return {
        "id": str(uuid4()),
        "content": content,
        "created_at": timezone.now().isoformat(),
        "contextual_tools": contextual_tools,
        "ui_context": ui_context,
        "billing_context": billing_context,
        "agent_mode": agent_mode,
        "session_id": session_id,
    }
