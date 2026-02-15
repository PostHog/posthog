import time
import pickle
import asyncio
from collections.abc import AsyncGenerator, Callable
from typing import Literal, Optional, cast
from uuid import UUID

from django.conf import settings

import structlog
import redis.exceptions as redis_exceptions
from prometheus_client import Histogram
from pydantic import BaseModel, Field

from posthog.schema import (
    AssistantEventType,
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantUpdateEvent,
    SubagentUpdateEvent,
)

from posthog.redis import get_async_client

from ee.hogai.utils.types import AssistantOutput
from ee.hogai.utils.types.base import ApprovalPayload, AssistantStreamedMessageUnion
from ee.models.assistant import Conversation

logger = structlog.get_logger(__name__)

REDIS_TO_CLIENT_LATENCY_HISTOGRAM = Histogram(
    "posthog_ai_redis_to_client_latency_seconds",
    "Time from writing message to Redis stream to reading it on client side",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf")],
)

REDIS_READ_ITERATION_LATENCY_HISTOGRAM = Histogram(
    "posthog_ai_redis_read_iteration_latency_seconds",
    "Time between iterations in the Redis stream read loop",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf")],
)

REDIS_WRITE_ITERATION_LATENCY_HISTOGRAM = Histogram(
    "posthog_ai_redis_write_iteration_latency_seconds",
    "Time between iterations in the Redis stream write loop",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf")],
)

REDIS_STREAM_INIT_ITERATION_LATENCY_HISTOGRAM = Histogram(
    "posthog_ai_redis_stream_init_iteration_latency_seconds",
    "Time between iterations in the stream initialization wait loop",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf")],
)

# Redis stream configuration
CONVERSATION_STREAM_MAX_LENGTH = 1000  # Maximum number of messages to keep in stream
CONVERSATION_STREAM_CONCURRENT_READ_COUNT = 8
CONVERSATION_STREAM_PREFIX = "conversation-stream:"
CONVERSATION_STREAM_TIMEOUT = 30 * 60  # 30 minutes


class ConversationEvent(BaseModel):
    type: Literal["conversation"]
    payload: UUID  # conversation id


class MessageEvent(BaseModel):
    type: Literal[AssistantEventType.MESSAGE]
    payload: AssistantStreamedMessageUnion


class UpdateEvent(BaseModel):
    type: Literal[AssistantEventType.UPDATE]
    payload: AssistantUpdateEvent | SubagentUpdateEvent


class GenerationStatusEvent(BaseModel):
    type: Literal[AssistantEventType.STATUS]
    payload: AssistantGenerationStatusEvent


class StatusPayload(BaseModel):
    status: Literal["complete", "error"]
    error: Optional[str] = None


class StreamStatusEvent(BaseModel):
    type: Literal["STREAM_STATUS"] = "STREAM_STATUS"
    payload: StatusPayload


class ApprovalEvent(BaseModel):
    type: Literal[AssistantEventType.APPROVAL]
    payload: ApprovalPayload


StreamEventUnion = (
    ConversationEvent | MessageEvent | GenerationStatusEvent | UpdateEvent | StreamStatusEvent | ApprovalEvent
)


class StreamEvent(BaseModel):
    event: StreamEventUnion = Field(discriminator="type")
    timestamp: float = Field(default_factory=time.time)


def get_conversation_stream_key(conversation_id: UUID) -> str:
    """Get the Redis stream key for a conversation."""
    return f"{CONVERSATION_STREAM_PREFIX}{conversation_id}"


def get_subagent_stream_key(conversation_id: UUID, tool_call_id: str) -> str:
    """Get the Redis stream key for a subagent tool execution."""
    return f"{CONVERSATION_STREAM_PREFIX}{conversation_id}:{tool_call_id}"


class ConversationStreamSerializer:
    serialization_key = "data"

    def dumps(self, event: AssistantOutput | StatusPayload) -> dict[str, bytes] | None:
        """Serialize an event to a dictionary of bytes.

        Args:
            event: AssistantOutput or RedisStreamStatus

        Returns:
            Dictionary of bytes
        """
        if isinstance(event, StatusPayload):
            return self._serialize(
                StreamStatusEvent(
                    payload=event,
                )
            )
        else:
            event_type, event_data = event
            if event_type == AssistantEventType.MESSAGE:
                return self._serialize(self._to_message_event(cast(AssistantStreamedMessageUnion, event_data)))
            elif event_type == AssistantEventType.CONVERSATION:
                return self._serialize(self._to_conversation_event(cast(Conversation, event_data)))
            elif event_type == AssistantEventType.STATUS:
                return self._serialize(self._to_status_event(cast(AssistantGenerationStatusEvent, event_data)))
            elif event_type == AssistantEventType.UPDATE:
                return self._serialize(
                    self._to_update_event(cast(AssistantUpdateEvent | SubagentUpdateEvent, event_data))
                )
            elif event_type == AssistantEventType.APPROVAL:
                return self._serialize(self._to_approval_event(cast(ApprovalPayload, event_data)))
            else:
                raise ValueError(f"Unknown event type: {event_type}")

    def _serialize(self, event: StreamEventUnion | None) -> dict[str, bytes] | None:
        if event is None:
            return None

        return {
            # nosemgrep: python.lang.security.deserialization.pickle.avoid-pickle (internal Redis stream, data is self-generated)
            self.serialization_key: pickle.dumps(
                StreamEvent(
                    event=event,
                )
            ),
        }

    def _to_message_event(self, message: AssistantStreamedMessageUnion) -> MessageEvent:
        return MessageEvent(
            type=AssistantEventType.MESSAGE,
            payload=message,
        )

    def _to_conversation_event(self, conversation: Conversation) -> ConversationEvent:
        return ConversationEvent(
            type="conversation",
            payload=conversation.id,
        )

    def _to_status_event(self, event: AssistantGenerationStatusEvent) -> GenerationStatusEvent | None:
        if isinstance(event, AssistantGenerationStatusEvent) and event.type == AssistantGenerationStatusType.ACK:
            # we don't need to send ACK messages to the client
            # they are only used to trigger temporal heartbeats
            return None

        return GenerationStatusEvent(
            type=AssistantEventType.STATUS,
            payload=event,
        )

    def _to_update_event(self, update: AssistantUpdateEvent | SubagentUpdateEvent) -> UpdateEvent:
        return UpdateEvent(
            type=AssistantEventType.UPDATE,
            payload=update,
        )

    def _to_approval_event(self, approval: ApprovalPayload) -> ApprovalEvent:
        return ApprovalEvent(
            type=AssistantEventType.APPROVAL,
            payload=approval,
        )

    def deserialize(self, data: dict[bytes, bytes]) -> StreamEvent:
        # nosemgrep: python.lang.security.deserialization.pickle.avoid-pickle (internal Redis stream, data is self-generated)
        return pickle.loads(data[bytes(self.serialization_key, "utf-8")])


class StreamError(Exception):
    """Raised when there is an error with the Redis stream."""

    pass


class ConversationRedisStream:
    """Manages conversation streaming from Redis streams."""

    def __init__(
        self,
        stream_key: str,
        timeout: int = CONVERSATION_STREAM_TIMEOUT,
        max_length: int = CONVERSATION_STREAM_MAX_LENGTH,
    ):
        self._stream_key = stream_key
        self._redis_client = get_async_client(settings.REDIS_URL)
        self._deletion_lock = asyncio.Lock()
        self._serializer = ConversationStreamSerializer()
        self._timeout = timeout
        self._max_length = max_length

    async def wait_for_stream(self) -> bool:
        """Wait for stream to be created using linear backoff.

        Returns:
            True if stream was created, False otherwise
        """
        delay = 0.05  # Start with 50ms
        delay_increment = 0.15  # Increment by 150ms each attempt
        max_delay = 2.0  # Cap at 2 seconds
        timeout = 60.0  # 60 seconds timeout
        start_time = asyncio.get_event_loop().time()
        last_iteration_time = None

        while True:
            current_time = time.time()
            if last_iteration_time is not None:
                iteration_duration = current_time - last_iteration_time
                REDIS_STREAM_INIT_ITERATION_LATENCY_HISTOGRAM.observe(iteration_duration)
            last_iteration_time = current_time

            elapsed_time = asyncio.get_event_loop().time() - start_time
            if elapsed_time >= timeout:
                logger.debug(
                    f"Stream creation timeout after {elapsed_time:.2f}s",
                    stream_key=self._stream_key,
                )
                return False

            if await self._redis_client.exists(self._stream_key):
                return True

            logger.debug(
                f"Stream not found, retrying in {delay}s (elapsed: {elapsed_time:.2f}s)",
                stream_key=self._stream_key,
            )
            await asyncio.sleep(delay)

            # Linear backoff
            delay = min(delay + delay_increment, max_delay)

    async def read_stream(
        self,
        start_id: str = "0",
        block_ms: int = 50,  # Block for 50ms waiting for new messages
        count: Optional[int] = CONVERSATION_STREAM_CONCURRENT_READ_COUNT,
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        Read updates from Redis stream.

        Args:
            start_id: Stream ID to start reading from ("0" for beginning, "$" for new messages)
            block_ms: How long to block waiting for new messages (milliseconds)
            count: Maximum number of messages to read

        Yields:
            RedisStreamEvent
        """
        current_id = start_id
        start_time = asyncio.get_event_loop().time()
        last_iteration_time = None

        while True:
            current_time = time.time()
            if last_iteration_time is not None:
                iteration_duration = current_time - last_iteration_time
                REDIS_READ_ITERATION_LATENCY_HISTOGRAM.observe(iteration_duration)
            last_iteration_time = current_time

            if asyncio.get_event_loop().time() - start_time > self._timeout:
                raise StreamError("Stream timeout - conversation took too long to complete")

            try:
                messages = await self._redis_client.xread(
                    {self._stream_key: current_id},
                    block=block_ms,
                    count=count,
                )

                if not messages:
                    # No new messages after blocking, continue polling
                    continue

                for _, stream_messages in messages:
                    for stream_id, message in stream_messages:
                        current_id = stream_id
                        data = self._serializer.deserialize(message)

                        latency = time.time() - data.timestamp
                        REDIS_TO_CLIENT_LATENCY_HISTOGRAM.observe(latency)

                        if isinstance(data.event, StreamStatusEvent):
                            if data.event.payload.status == "complete":
                                return
                            elif data.event.payload.status == "error":
                                error = data.event.payload.error or "Unknown error"
                                if error:
                                    raise StreamError(error)
                                continue

                        else:
                            yield data

            except redis_exceptions.ConnectionError:
                raise StreamError("Connection lost to conversation stream")
            except redis_exceptions.TimeoutError:
                raise StreamError("Stream read timeout")
            except redis_exceptions.RedisError:
                raise StreamError("Stream read error")
            except Exception:
                raise StreamError("Unexpected error reading conversation stream")

    async def delete_stream(self) -> bool:
        """Delete the Redis stream for this conversation.

        Returns:
            True if stream was deleted, False otherwise
        """
        async with self._deletion_lock:
            try:
                return await self._redis_client.delete(self._stream_key) > 0
            except Exception:
                logger.exception("Failed to delete stream", stream_key=self._stream_key)
                return False

    async def mark_complete(self) -> None:
        await self._write_status(StatusPayload(status="complete"))

    async def _write_status(self, status: StatusPayload) -> None:
        message = self._serializer.dumps(status)
        if message is None:
            return
        await self._redis_client.xadd(
            self._stream_key,
            message,
            maxlen=self._max_length,
            approximate=True,
        )

    async def write_to_stream(
        self,
        generator: AsyncGenerator[AssistantOutput, None],
        callback: Callable[[], None] | None = None,
        emit_completion: bool = True,
    ) -> None:
        """Write to the Redis stream.

        Args:
            generator: AsyncGenerator of AssistantOutput
            callback: Callback to trigger after each message is written to the stream
            emit_completion: Whether to mark the stream as complete
        """
        try:
            await self._redis_client.expire(self._stream_key, self._timeout)

            last_iteration_time = None
            async for chunk in generator:
                current_time = time.time()
                if last_iteration_time is not None:
                    iteration_duration = current_time - last_iteration_time
                    REDIS_WRITE_ITERATION_LATENCY_HISTOGRAM.observe(iteration_duration)
                last_iteration_time = current_time

                message = self._serializer.dumps(chunk)
                if message is not None:
                    await self._redis_client.xadd(
                        self._stream_key,
                        message,
                        maxlen=self._max_length,
                        approximate=True,
                    )
                if callback:
                    callback()

            if emit_completion:
                await self._write_status(StatusPayload(status="complete"))

        except Exception as e:
            await self._write_status(StatusPayload(status="error", error=str(e)))
            raise StreamError("Failed to write to stream")
