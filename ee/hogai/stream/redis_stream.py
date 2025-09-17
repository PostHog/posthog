import pickle
import asyncio
from collections.abc import AsyncGenerator, Callable
from typing import Literal, Optional, cast
from uuid import UUID

from django.conf import settings

import structlog
import redis.exceptions as redis_exceptions
from pydantic import BaseModel, Field

from posthog.schema import AssistantEventType, AssistantGenerationStatusEvent, AssistantGenerationStatusType

from posthog.redis import get_async_client

from ee.hogai.utils.types import AssistantMessageOrStatusUnion, AssistantOutput
from ee.models.assistant import Conversation

logger = structlog.get_logger(__name__)


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
    payload: AssistantMessageOrStatusUnion


class StatusPayload(BaseModel):
    status: Literal["complete", "error"]
    error: Optional[str] = None


class StatusEvent(BaseModel):
    type: Literal["status"]
    payload: StatusPayload


StreamEventUnion = ConversationEvent | MessageEvent | StatusEvent


class StreamEvent(BaseModel):
    event: StreamEventUnion = Field(discriminator="type")


def get_conversation_stream_key(conversation_id: UUID) -> str:
    """Get the Redis stream key for a conversation."""
    return f"{CONVERSATION_STREAM_PREFIX}{conversation_id}"


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
                StatusEvent(
                    type="status",
                    payload=event,
                )
            )
        else:
            event_type, event_data = event
            if event_type == AssistantEventType.MESSAGE:
                return self._serialize(self._to_message_event(cast(AssistantMessageOrStatusUnion, event_data)))
            elif event_type == AssistantEventType.CONVERSATION:
                return self._serialize(self.to_conversation_event(cast(Conversation, event_data)))
            else:
                raise ValueError(f"Unknown event type: {event_type}")

    def _serialize(self, event: StreamEventUnion | None) -> dict[str, bytes] | None:
        if event is None:
            return None

        return {
            self.serialization_key: pickle.dumps(
                StreamEvent(
                    event=event,
                )
            ),
        }

    def _to_message_event(self, message: AssistantMessageOrStatusUnion) -> MessageEvent | None:
        if isinstance(message, AssistantGenerationStatusEvent) and message.type == AssistantGenerationStatusType.ACK:
            # we don't need to send ACK messages to the client
            # they are only used to trigger temporal heartbeats
            return None

        return MessageEvent(
            type=AssistantEventType.MESSAGE,
            payload=message,
        )

    def to_conversation_event(self, conversation: Conversation) -> ConversationEvent:
        return ConversationEvent(
            type="conversation",
            payload=conversation.id,
        )

    def deserialize(self, data: dict[bytes, bytes]) -> StreamEvent:
        return pickle.loads(data[bytes(self.serialization_key, "utf-8")])


class StreamError(Exception):
    """Raised when there is an error with the Redis stream."""

    pass


class ConversationRedisStream:
    """Manages conversation streaming from Redis streams."""

    def __init__(self, stream_key: str):
        self._stream_key = stream_key
        self._redis_client = get_async_client(settings.REDIS_URL)
        self._deletion_lock = asyncio.Lock()
        self._serializer = ConversationStreamSerializer()

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

        while True:
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

        while True:
            if asyncio.get_event_loop().time() - start_time > CONVERSATION_STREAM_TIMEOUT:
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

                        if isinstance(data.event, StatusEvent):
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

    async def write_to_stream(
        self, generator: AsyncGenerator[AssistantOutput, None], callback: Callable[[], None] | None = None
    ) -> None:
        """Write to the Redis stream.

        Args:
            generator: AsyncGenerator of AssistantOutput
            callback: Callback to trigger after each message is written to the stream
        """
        try:
            await self._redis_client.expire(self._stream_key, CONVERSATION_STREAM_TIMEOUT)

            async for chunk in generator:
                message = self._serializer.dumps(chunk)
                if message is not None:
                    await self._redis_client.xadd(
                        self._stream_key,
                        message,
                        maxlen=CONVERSATION_STREAM_MAX_LENGTH,
                        approximate=True,
                    )
                if callback:
                    callback()

            # Mark the stream as complete
            status_message = StatusPayload(status="complete")
            completion_message = self._serializer.dumps(status_message)
            await self._redis_client.xadd(
                self._stream_key,
                completion_message,
                maxlen=CONVERSATION_STREAM_MAX_LENGTH,
                approximate=True,
            )

        except Exception as e:
            # Mark the stream as failed
            error_message = StatusPayload(status="error", error=str(e))
            message = self._serializer.dumps(error_message)
            await self._redis_client.xadd(
                self._stream_key,
                message,
                maxlen=CONVERSATION_STREAM_MAX_LENGTH,
                approximate=True,
            )
            raise StreamError("Failed to write to stream")
