import asyncio
from typing import cast
import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import redis.exceptions as redis_exceptions

from ee.hogai.stream.redis_stream import (
    REDIS_STREAM_EXPIRATION_TIME,
    RedisStream,
    RedisStreamError,
    RedisStreamEvent,
    RedisStreamMessageData,
    RedisStreamStatus,
    RedisStreamStatusData,
    RedisStreamSerializer,
)
from ee.models.assistant import Conversation
from posthog.schema import AssistantEventType, AssistantMessage
from posthog.test.base import BaseTest


class TestRedisStream(BaseTest):
    def setUp(self):
        self.stream_key = f"test_stream:{uuid4()}"
        self.redis_stream = RedisStream(self.stream_key)

    @patch("ee.hogai.stream.redis_stream.get_async_client")
    def test_init(self, mock_get_client):
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        stream = RedisStream(self.stream_key)

        self.assertEqual(stream._stream_key, self.stream_key)
        self.assertIsNotNone(stream._redis_client)

    @pytest.mark.asyncio
    async def test_wait_for_stream_creation_success(self):
        with patch.object(self.redis_stream, "_redis_client") as mock_client:
            mock_client.exists = AsyncMock(return_value=True)

            result = await self.redis_stream.wait_for_stream_creation()

            self.assertTrue(result)
            mock_client.exists.assert_called_once_with(self.stream_key)

    @pytest.mark.asyncio
    async def test_wait_for_stream_creation_timeout(self):
        with patch.object(self.redis_stream, "_redis_client") as mock_client:
            mock_client.exists = AsyncMock(return_value=False)

            with patch("asyncio.sleep", new_callable=AsyncMock):
                with patch("ee.hogai.stream.redis_stream.asyncio.get_event_loop") as mock_get_loop:
                    from unittest.mock import MagicMock

                    mock_loop = MagicMock()
                    mock_get_loop.return_value = mock_loop
                    # Mock time to simulate timeout after 60 seconds
                    # First call (start_time), second call (elapsed_time check)
                    mock_loop.time.side_effect = [0, 61]  # Start at 0, then 61 seconds later

                    result = await self.redis_stream.wait_for_stream_creation()

                    self.assertFalse(result)
                    # The function should timeout immediately without calling stream exists
                    self.assertEqual(mock_client.exists.call_count, 0)

    @pytest.mark.asyncio
    async def test_read_stream_with_data(self):
        with patch.object(self.redis_stream, "_redis_client") as mock_client:
            # Mock serialized data
            import pickle

            test_event = RedisStreamEvent(
                event=RedisStreamMessageData(type=AssistantEventType.MESSAGE, payload=AssistantMessage(content="test")),
                timestamp="1234567890",
            )
            serialized_data = pickle.dumps(test_event)
            mock_client.xread = AsyncMock(return_value=[(self.stream_key, [(b"1234-0", {b"data": serialized_data})])])

            chunks = []
            async for chunk in self.redis_stream.read_stream():
                chunks.append(chunk)
                break  # Only get first chunk

            self.assertEqual(len(chunks), 1)
            self.assertEqual(chunks[0].event.type, AssistantEventType.MESSAGE)

    @pytest.mark.asyncio
    async def test_read_stream_completion_status(self):
        with patch.object(self.redis_stream, "_redis_client") as mock_client:
            # Mock xread to return completion status
            import pickle

            test_event = RedisStreamEvent(
                event=RedisStreamStatusData(type="status", payload=RedisStreamStatus(status="complete")),
                timestamp="1234567890",
            )
            serialized_data = pickle.dumps(test_event)
            mock_client.xread = AsyncMock(return_value=[(self.stream_key, [(b"1234-0", {b"data": serialized_data})])])

            chunks = []
            async for chunk in self.redis_stream.read_stream():
                chunks.append(chunk)

            self.assertEqual(chunks, [])  # No data chunks, just completion

    @pytest.mark.asyncio
    async def test_read_stream_error_status(self):
        # Test that RedisStreamError is raised when there's an error status
        with patch.object(self.redis_stream, "_redis_client") as mock_client:
            import pickle

            test_event = RedisStreamEvent(
                event=RedisStreamStatusData(
                    type="status", payload=RedisStreamStatus(status="error", error="Test error")
                ),
                timestamp="1234567890",
            )
            serialized_data = pickle.dumps(test_event)
            mock_client.xread = AsyncMock(return_value=[(self.stream_key, [(b"1234-0", {b"data": serialized_data})])])

            with self.assertRaises(RedisStreamError) as context:
                async for _ in self.redis_stream.read_stream():
                    pass

            self.assertIn("Unexpected error reading", str(context.exception))

    @pytest.mark.asyncio
    async def test_read_stream_timeout(self):
        with patch.object(self.redis_stream, "_redis_client") as mock_client:
            # Mock xread to return no messages indefinitely
            mock_client.xread = AsyncMock(return_value=[])

            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.time.side_effect = [0, REDIS_STREAM_EXPIRATION_TIME + 1]

                with self.assertRaises(RedisStreamError) as context:
                    async for _ in self.redis_stream.read_stream():
                        pass

                self.assertIn("Stream timeout", str(context.exception))

    @pytest.mark.asyncio
    async def test_read_stream_connection_error(self):
        with patch.object(self.redis_stream, "_redis_client") as mock_client:
            # Mock xread to raise connection error
            mock_client.xread = AsyncMock(side_effect=redis_exceptions.ConnectionError("Connection lost"))

            with self.assertRaises(RedisStreamError) as context:
                async for _ in self.redis_stream.read_stream():
                    pass

            self.assertIn("Connection lost", str(context.exception))

    @pytest.mark.asyncio
    async def test_read_stream_redis_timeout_error(self):
        with patch.object(self.redis_stream, "_redis_client") as mock_client:
            # Mock xread to raise timeout error
            mock_client.xread = AsyncMock(side_effect=redis_exceptions.TimeoutError("Timeout"))

            with self.assertRaises(RedisStreamError) as context:
                async for _ in self.redis_stream.read_stream():
                    pass

            self.assertIn("Stream read timeout", str(context.exception))

    @pytest.mark.asyncio
    async def test_read_stream_generic_redis_error(self):
        with patch.object(self.redis_stream, "_redis_client") as mock_client:
            # Mock xread to raise generic Redis error
            mock_client.xread = AsyncMock(side_effect=redis_exceptions.RedisError("Redis error"))

            with self.assertRaises(RedisStreamError) as context:
                async for _ in self.redis_stream.read_stream():
                    pass

            self.assertIn("Stream read error", str(context.exception))

    @pytest.mark.asyncio
    async def test_read_stream_unexpected_error(self):
        with patch.object(self.redis_stream, "_redis_client") as mock_client:
            # Mock xread to raise unexpected error
            mock_client.xread = AsyncMock(side_effect=ValueError("Unexpected error"))

            with self.assertRaises(RedisStreamError) as context:
                async for _ in self.redis_stream.read_stream():
                    pass

            self.assertIn("Unexpected error reading", str(context.exception))

    @pytest.mark.asyncio
    async def test_delete_stream_success(self):
        with patch.object(self.redis_stream, "_redis_client") as mock_client:
            mock_client.delete = AsyncMock(return_value=1)  # Successfully deleted

            result = await self.redis_stream.delete_stream()

            self.assertTrue(result)
            mock_client.delete.assert_called_once_with(self.stream_key)

    @pytest.mark.asyncio
    async def test_delete_stream_not_found(self):
        with patch.object(self.redis_stream, "_redis_client") as mock_client:
            mock_client.delete = AsyncMock(return_value=0)  # Stream not found
            result = await self.redis_stream.delete_stream()
            self.assertFalse(result)

    @pytest.mark.asyncio
    async def test_delete_stream_already_deleted(self):
        with patch.object(self.redis_stream, "_redis_client") as mock_client:
            mock_client.delete = AsyncMock(return_value=0)  # Stream doesn't exist
            result = await self.redis_stream.delete_stream()

            self.assertFalse(result)
            mock_client.delete.assert_called_once_with(self.stream_key)

    @pytest.mark.asyncio
    async def test_delete_stream_exception(self):
        with patch.object(self.redis_stream, "_redis_client") as mock_client:
            mock_client.delete = AsyncMock(side_effect=Exception("Redis error"))
            result = await self.redis_stream.delete_stream()
            self.assertFalse(result)

    @pytest.mark.asyncio
    async def test_read_stream_no_messages_continue_polling(self):
        with patch.object(self.redis_stream, "_redis_client") as mock_client:
            # First call returns no messages, second call returns data
            import pickle

            test_event = RedisStreamEvent(
                event=RedisStreamMessageData(
                    type=AssistantEventType.MESSAGE, payload=AssistantMessage(content="test chunk")
                ),
                timestamp="1234567890",
            )
            serialized_data = pickle.dumps(test_event)
            mock_client.xread = AsyncMock(
                side_effect=[
                    [],  # No messages
                    [(self.stream_key, [(b"1234-0", {b"data": serialized_data})])],  # Data
                ]
            )

            chunks = []
            async for chunk in self.redis_stream.read_stream():
                chunks.append(chunk)
                break  # Only get first chunk

            self.assertEqual(len(chunks), 1)
            self.assertEqual(chunks[0].event.type, AssistantEventType.MESSAGE)
            self.assertEqual(mock_client.xread.call_count, 2)

    @pytest.mark.asyncio
    async def test_read_stream_multiple_messages(self):
        with patch.object(self.redis_stream, "_redis_client") as mock_client:
            # Mock xread to return multiple messages
            import pickle

            test_event1 = RedisStreamEvent(
                event=RedisStreamMessageData(
                    type=AssistantEventType.MESSAGE, payload=AssistantMessage(content="chunk 1")
                ),
                timestamp="1234567890",
            )
            test_event2 = RedisStreamEvent(
                event=RedisStreamMessageData(
                    type=AssistantEventType.MESSAGE, payload=AssistantMessage(content="chunk 2")
                ),
                timestamp="1234567891",
            )
            complete_event = RedisStreamEvent(
                event=RedisStreamStatusData(type="status", payload=RedisStreamStatus(status="complete")),
                timestamp="1234567892",
            )
            mock_client.xread = AsyncMock(
                return_value=[
                    (
                        self.stream_key,
                        [
                            (b"1234-0", {b"data": pickle.dumps(test_event1)}),
                            (b"1234-1", {b"data": pickle.dumps(test_event2)}),
                            (b"1234-2", {b"data": pickle.dumps(complete_event)}),
                        ],
                    )
                ]
            )

            chunks = []
            async for chunk in self.redis_stream.read_stream():
                chunks.append(chunk)

            self.assertEqual(len(chunks), 2)
            self.assertEqual(chunks[0].event.type, AssistantEventType.MESSAGE)
            self.assertEqual(chunks[1].event.type, AssistantEventType.MESSAGE)

    @pytest.mark.asyncio
    async def test_read_stream_invalid_data_skipped(self):
        with patch.object(self.redis_stream, "_redis_client") as mock_client:
            # Mock xread to return invalid serialized data
            import pickle

            valid_event = RedisStreamEvent(
                event=RedisStreamMessageData(
                    type=AssistantEventType.MESSAGE, payload=AssistantMessage(content="valid chunk")
                ),
                timestamp="1234567890",
            )
            complete_event = RedisStreamEvent(
                event=RedisStreamStatusData(type="status", payload=RedisStreamStatus(status="complete")),
                timestamp="1234567891",
            )
            mock_client.xread = AsyncMock(
                return_value=[
                    (
                        self.stream_key,
                        [
                            (b"1234-0", {b"data": b"\xff\xfe"}),  # Invalid pickle data
                            (b"1234-1", {b"data": pickle.dumps(valid_event)}),
                            (b"1234-2", {b"data": pickle.dumps(complete_event)}),
                        ],
                    )
                ]
            )

            with self.assertRaises(Exception):  # Should raise exception on invalid data
                chunks = []
                async for chunk in self.redis_stream.read_stream():
                    chunks.append(chunk)

    @pytest.mark.asyncio
    async def test_write_to_stream_success(self):
        with patch.object(self.redis_stream, "_redis_client") as mock_client:
            mock_client.xadd = AsyncMock()
            mock_client.expire = AsyncMock()

            # Create a test generator
            async def test_generator():
                yield (AssistantEventType.MESSAGE, AssistantMessage(content="test message 1"))
                yield (AssistantEventType.MESSAGE, AssistantMessage(content="test message 2"))

            await self.redis_stream.write_to_stream(test_generator())

            # Should call xadd 3 times: 2 data messages + 1 completion
            self.assertEqual(mock_client.xadd.call_count, 3)
            mock_client.expire.assert_called_once_with(self.stream_key, REDIS_STREAM_EXPIRATION_TIME)

    @pytest.mark.asyncio
    async def test_write_to_stream_exception(self):
        with patch.object(self.redis_stream, "_redis_client") as mock_client:
            mock_client.xadd = AsyncMock(side_effect=Exception("Redis error"))

            async def test_generator():
                yield (AssistantEventType.MESSAGE, AssistantMessage(content="test message"))

            with self.assertRaises(Exception):
                await self.redis_stream.write_to_stream(test_generator())

            # Should call xadd twice: 1 failed data message + 1 error status
            self.assertEqual(mock_client.xadd.call_count, 2)

    @pytest.mark.asyncio
    async def test_write_to_stream_empty_generator(self):
        with patch.object(self.redis_stream, "_redis_client") as mock_client:
            mock_client.xadd = AsyncMock()
            mock_client.expire = AsyncMock()

            async def empty_generator():
                return
                yield  # This will never be reached

            await self.redis_stream.write_to_stream(empty_generator())

            # Should call xadd once for completion status
            self.assertEqual(mock_client.xadd.call_count, 1)
            mock_client.expire.assert_called_once_with(self.stream_key, REDIS_STREAM_EXPIRATION_TIME)

    @pytest.mark.asyncio
    async def test_context_manager_enter_exit(self):
        # Test __aenter__ and __aexit__ methods
        with patch.object(self.redis_stream, "_redis_client") as mock_client:
            mock_client.close = AsyncMock()

            async with self.redis_stream as stream:
                self.assertEqual(stream, self.redis_stream)

            mock_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_with_exception(self):
        # Test __aexit__ when an exception occurs
        with patch.object(self.redis_stream, "_redis_client") as mock_client:
            mock_client.close = AsyncMock()

            try:
                async with self.redis_stream:
                    raise ValueError("Test exception")
            except ValueError:
                pass

            mock_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_serializer_integration(self):
        # Test that the serializer is properly integrated
        with patch.object(self.redis_stream, "_redis_client") as mock_client:
            mock_client.xadd = AsyncMock()
            mock_client.expire = AsyncMock()

            # Test with a real serializer
            async def test_generator():
                yield (AssistantEventType.MESSAGE, AssistantMessage(content="test"))

            await self.redis_stream.write_to_stream(test_generator())

            # Check that xadd was called with serialized data
            calls = mock_client.xadd.call_args_list
            self.assertEqual(len(calls), 2)  # 1 data + 1 completion

            # First call should be the data message
            first_call = calls[0]
            self.assertEqual(first_call[0][0], self.stream_key)  # stream key
            self.assertIn("data", first_call[0][1])  # message contains 'data' key

            # Second call should be the completion message
            second_call = calls[1]
            self.assertEqual(second_call[0][0], self.stream_key)  # stream key
            self.assertIn("data", second_call[0][1])  # completion message contains 'data' key

    @pytest.mark.asyncio
    async def test_deletion_lock_concurrency(self):
        # Test that deletion lock works properly
        with patch.object(self.redis_stream, "_redis_client") as mock_client:
            mock_client.delete = AsyncMock()

            # Create multiple concurrent deletion attempts
            async def delete_task():
                return await self.redis_stream.delete_stream()

            tasks = [delete_task() for _ in range(5)]
            results = await asyncio.gather(*tasks)

            # All should succeed (or fail consistently)
            self.assertEqual(len(results), 5)
            # delete should be called multiple times, but serialized by the lock
            self.assertEqual(mock_client.delete.call_count, 5)

    def test_serializer_message_serialization(self):
        # Test RedisStreamSerializer with message data
        serializer = RedisStreamSerializer()

        # Test message serialization with proper AssistantMessage format
        message_data = AssistantMessage(content="test message")
        event = (AssistantEventType.MESSAGE, message_data)

        serialized = serializer.dumps(event)
        self.assertIn("data", serialized)
        self.assertIsInstance(serialized["data"], bytes)

        # Test deserialization - need to convert string keys to bytes
        bytes_data = {bytes(k, "utf-8"): v for k, v in serialized.items()}
        deserialized = serializer.deserialize(bytes_data)
        self.assertEqual(deserialized.event.type, AssistantEventType.MESSAGE)
        payload = cast(AssistantMessage, deserialized.event.payload)
        self.assertEqual(payload.content, message_data.content)
        self.assertEqual(payload.type, message_data.type)
        self.assertIsInstance(deserialized.timestamp, str)

    def test_serializer_conversation_serialization(self):
        serializer = RedisStreamSerializer()
        conversation = Conversation.objects.create(team=self.team, user=self.user)
        event = (AssistantEventType.CONVERSATION, conversation)
        serialized = serializer.dumps(event)
        self.assertIn("data", serialized)
        self.assertIsInstance(serialized["data"], bytes)

        bytes_data = {bytes(k, "utf-8"): v for k, v in serialized.items()}
        deserialized = serializer.deserialize(bytes_data)
        self.assertEqual(deserialized.event.type, AssistantEventType.CONVERSATION)
        self.assertEqual(deserialized.event.payload, conversation.id)
        self.assertIsInstance(deserialized.timestamp, str)

    def test_serializer_status_serialization(self):
        # Test RedisStreamSerializer with status data
        serializer = RedisStreamSerializer()

        # Test status serialization
        status = RedisStreamStatus(status="complete")
        serialized = serializer.dumps(status)
        self.assertIn("data", serialized)
        self.assertIsInstance(serialized["data"], bytes)

        # Test deserialization - need to convert string keys to bytes
        bytes_data = {bytes(k, "utf-8"): v for k, v in serialized.items()}
        deserialized = serializer.deserialize(bytes_data)
        self.assertEqual(deserialized.event.type, "status")
        payload = cast(RedisStreamStatus, deserialized.event.payload)
        self.assertEqual(payload.status, "complete")
        self.assertIsNone(payload.error)

    def test_serializer_error_status_serialization(self):
        # Test RedisStreamSerializer with error status
        serializer = RedisStreamSerializer()

        # Test error status serialization
        status = RedisStreamStatus(status="error", error="Test error message")
        serialized = serializer.dumps(status)
        self.assertIn("data", serialized)
        self.assertIsInstance(serialized["data"], bytes)

        # Test deserialization - need to convert string keys to bytes
        bytes_data = {bytes(k, "utf-8"): v for k, v in serialized.items()}
        deserialized = serializer.deserialize(bytes_data)
        self.assertEqual(deserialized.event.type, "status")
        payload = cast(RedisStreamStatus, deserialized.event.payload)
        self.assertEqual(payload.status, "error")
        self.assertEqual(payload.error, "Test error message")

    def test_serializer_unknown_event_type(self):
        # Test RedisStreamSerializer with unknown event type
        serializer = RedisStreamSerializer()

        # Test unknown event type
        unknown_event = ("unknown_type", {"data": "test"})

        with self.assertRaises(ValueError) as context:
            serializer.dumps(unknown_event)  # type: ignore

        self.assertIn("Unknown event type", str(context.exception))
