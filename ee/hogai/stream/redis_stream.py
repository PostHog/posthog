import asyncio
import structlog
from typing import Literal, Optional, cast
from collections.abc import AsyncGenerator

import redis.exceptions as redis_exceptions
from django.conf import settings

from ee.hogai.utils.types import AssistantMessageUnion, AssistantOutput
from posthog.redis import get_async_client
import pickle
from time import time
from uuid import UUID

from pydantic import BaseModel

from ee.models.assistant import Conversation
from posthog.schema import AssistantEventType
from pydantic import Field

logger = structlog.get_logger(__name__)


# Redis stream configuration
REDIS_STREAM_MAX_LENGTH = 1000  # Maximum number of messages to keep in stream
REDIS_STREAM_EXPIRATION_TIME = 30 * 60  # 30 minutes
REDIS_STREAM_CONCURRENT_READ_COUNT = 8


class RedisStreamConversationData(BaseModel):
    type: Literal["conversation"]
    payload: UUID  # conversation id


class RedisStreamMessageData(BaseModel):
    type: Literal[AssistantEventType.MESSAGE]
    payload: AssistantMessageUnion


class RedisStreamStatus(BaseModel):
    status: Literal["complete", "error"]
    error: Optional[str] = None


class RedisStreamStatusData(BaseModel):
    type: Literal["status"]
    payload: RedisStreamStatus


RedisStreamEventPayload = RedisStreamConversationData | RedisStreamMessageData | RedisStreamStatusData


class RedisStreamEvent(BaseModel):
    event: RedisStreamEventPayload = Field(discriminator="type")
    timestamp: str


class RedisStreamSerializer:
    serialization_key = "data"

    def dumps(self, event: AssistantOutput | RedisStreamStatus) -> dict[str, bytes]:
        """Serialize an event to a dictionary of bytes.

        Args:
            event: AssistantOutput or RedisStreamStatus

        Returns:
            Dictionary of bytes
        """
        if isinstance(event, RedisStreamStatus):
            return self._serialize(
                RedisStreamStatusData(
                    type="status",
                    payload=event,
                )
            )
        else:
            event_type, event_data = event
            if event_type == AssistantEventType.MESSAGE:
                return self._serialize(self._convert_to_message_data(cast(AssistantMessageUnion, event_data)))
            elif event_type == AssistantEventType.CONVERSATION:
                return self._serialize(self._convert_to_conversation_data(cast(Conversation, event_data)))
            else:
                raise ValueError(f"Unknown event type: {event_type}")

    def _serialize(self, event: RedisStreamEventPayload) -> dict[str, bytes]:
        return {
            self.serialization_key: pickle.dumps(
                RedisStreamEvent(
                    event=event,
                    timestamp=str(int(time() * 1000)),
                )
            ),
        }

    def _convert_to_message_data(self, message: AssistantMessageUnion) -> RedisStreamMessageData:
        return RedisStreamMessageData(
            type=AssistantEventType.MESSAGE,
            payload=message,
        )

    def _convert_to_conversation_data(self, conversation: Conversation) -> RedisStreamConversationData:
        return RedisStreamConversationData(
            type="conversation",
            payload=conversation.id,
        )

    def deserialize(self, data: dict[bytes, bytes]) -> RedisStreamEvent:
        return pickle.loads(data[bytes(self.serialization_key, "utf-8")])


class RedisStreamError(Exception):
    """Raised when there is an error with the Redis stream."""

    pass


class RedisStream:
    """Manages conversation streaming from Redis streams."""

    def __init__(self, stream_key: str):
        self._stream_key = stream_key
        self._redis_client = get_async_client(settings.REDIS_URL)
        self._deletion_lock = asyncio.Lock()
        self._serializer = RedisStreamSerializer()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._redis_client.close()

    async def wait_for_stream_creation(self) -> bool:
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
        count: Optional[int] = REDIS_STREAM_CONCURRENT_READ_COUNT,
    ) -> AsyncGenerator[RedisStreamEvent, None]:
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
            if asyncio.get_event_loop().time() - start_time > REDIS_STREAM_EXPIRATION_TIME:
                raise RedisStreamError("Stream timeout - conversation took too long to complete")

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

                        if isinstance(data.event, RedisStreamStatusData):
                            if data.event.payload.status == "complete":
                                return
                            elif data.event.payload.status == "error":
                                error = data.event.payload.error or "Unknown error"
                                if error:
                                    raise RedisStreamError(error)
                                continue

                        else:
                            yield data

            except redis_exceptions.ConnectionError:
                raise RedisStreamError("Connection lost to conversation stream")
            except redis_exceptions.TimeoutError:
                raise RedisStreamError("Stream read timeout")
            except redis_exceptions.RedisError:
                raise RedisStreamError("Stream read error")
            except Exception:
                raise RedisStreamError("Unexpected error reading conversation stream")

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

    async def write_to_stream(self, generator: AsyncGenerator[AssistantOutput, None]) -> None:
        """Write to the Redis stream.

        Args:
            generator: AsyncGenerator of AssistantOutput
        """
        try:
            async for chunk in generator:
                message = self._serializer.dumps(chunk)
                await self._redis_client.xadd(
                    self._stream_key,
                    message,
                    maxlen=REDIS_STREAM_MAX_LENGTH,
                    approximate=True,
                )

            # Mark the stream as complete
            status_message = RedisStreamStatus(status="complete")
            completion_message = self._serializer.dumps(status_message)
            await self._redis_client.xadd(
                self._stream_key,
                completion_message,
                maxlen=REDIS_STREAM_MAX_LENGTH,
                approximate=True,
            )

            await self._redis_client.expire(self._stream_key, REDIS_STREAM_EXPIRATION_TIME)

        except Exception as e:
            # Mark the stream as failed
            error_message = RedisStreamStatus(status="error", error=str(e))
            message = self._serializer.dumps(error_message)
            await self._redis_client.xadd(
                self._stream_key,
                message,
                maxlen=REDIS_STREAM_MAX_LENGTH,
                approximate=True,
            )
            raise RedisStreamError("Failed to write to stream")
