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


@dataclass
class ConversationQueueStore:
    conversation_id: str
    max_messages: int = MAX_QUEUE_MESSAGES
    cache_timeout_seconds: int = QUEUE_CACHE_TIMEOUT_SECONDS

    def _cache_key(self) -> str:
        return f"max_conversation_queue_{self.conversation_id}"

    def _lock_key(self) -> str:
        return f"{self._cache_key()}_lock"

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

    async def clear_async(self) -> builtins.list[ConversationQueueMessage]:
        async with self._async_lock():
            self.save([])
            return []

    def enqueue(self, message: ConversationQueueMessage) -> builtins.list[ConversationQueueMessage]:
        with self._lock():
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

    def pop_next(self) -> ConversationQueueMessage | None:
        with self._lock():
            queue = self.list()
            if not queue:
                return None
            message = queue.pop(0)
            self.save(queue)
            return message

    async def pop_next_async(self) -> ConversationQueueMessage | None:
        async with self._async_lock():
            queue = self.list()
            if not queue:
                return None
            message = queue.pop(0)
            self.save(queue)
            return message

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
