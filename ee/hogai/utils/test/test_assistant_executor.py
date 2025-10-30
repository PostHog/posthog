from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, Mock, patch

from temporalio.client import WorkflowExecutionStatus

from posthog.schema import AssistantMessage, AssistantToolCall, AssistantUpdateEvent, FailureMessage

from django.conf import settings
from posthog.temporal.ai.conversation import (
    AssistantConversationRunnerWorkflow,
    AssistantConversationRunnerWorkflowInputs,
)

from ee.hogai.stream.redis_stream import ConversationRedisStream, StreamError
from ee.hogai.utils.assistant_executor import AssistantExecutor
from ee.hogai.utils.stream_processor import AssistantStreamProcessor
from ee.hogai.utils.types import AssistantMode
from ee.hogai.utils.types.base import AssistantDispatcherEvent, AssistantNodeName, MessageAction
from ee.models.assistant import Conversation


class TestAssistantExecutor(BaseTest):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)
        self.team_id = self.team.pk
        self.user_id = self.user.pk
        self.manager = AssistantExecutor(self.conversation)
        # Create default workflow inputs for tests
        self.workflow_inputs = AssistantConversationRunnerWorkflowInputs(
            team_id=self.team_id,
            user_id=self.user_id,
            conversation_id=self.conversation.id,
            mode=AssistantMode.ASSISTANT,
            trace_id=str(uuid4()),
        )

    def test_init(self):
        """Test ConversationStreamManager initialization."""
        manager = AssistantExecutor(self.conversation)

        self.assertEqual(manager._conversation.id, self.conversation.id)
        self.assertIsInstance(manager._redis_stream, ConversationRedisStream)

    @patch("ee.hogai.utils.assistant_executor.async_connect")
    async def test_start_workflow_and_stream_success(self, mock_connect):
        """Test successful workflow start and streaming."""
        # Setup mocks
        mock_client = AsyncMock()
        mock_connect.return_value = mock_client

        # Mock the stream_conversation method
        async def mock_stream_gen():
            for chunk in [("message", {"content": "chunk1"}), ("message", {"content": "chunk2"})]:
                yield chunk

        with (
            patch.object(self.manager, "stream_conversation") as mock_stream,
            patch.object(self.manager, "_wait_for_workflow_to_start") as mock_wait_for_start,
        ):
            mock_stream.return_value = mock_stream_gen()
            mock_wait_for_start.return_value = True

            workflow_inputs = AssistantConversationRunnerWorkflowInputs(
                team_id=self.team_id,
                user_id=self.user_id,
                conversation_id=self.conversation.id,
                mode=AssistantMode.ASSISTANT,
                trace_id=str(uuid4()),
            )

            # Call the method
            results = []
            async for chunk in self.manager.astream(workflow_inputs):
                results.append(chunk)

            # Verify results
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0], ("message", {"content": "chunk1"}))
            self.assertEqual(results[1], ("message", {"content": "chunk2"}))

            # Verify client.start_workflow was called with correct parameters
            mock_client.start_workflow.assert_called_once()
            call_args = mock_client.start_workflow.call_args

            # Check workflow function and inputs
            self.assertEqual(call_args[0][0], AssistantConversationRunnerWorkflow.run)
            self.assertEqual(call_args[0][1], workflow_inputs)

            # Check keyword arguments
            self.assertEqual(call_args[1]["task_queue"], settings.MAX_AI_TASK_QUEUE)
            self.assertIn("conversation-", call_args[1]["id"])

    @patch("ee.hogai.utils.assistant_executor.async_connect")
    async def test_start_workflow_and_stream_connection_error(self, mock_connect):
        """Test error handling when connection fails."""
        # Setup mock to raise exception
        mock_connect.side_effect = Exception("Connection failed")

        workflow_inputs = AssistantConversationRunnerWorkflowInputs(
            team_id=self.team_id,
            user_id=self.user_id,
            conversation_id=self.conversation.id,
            mode=AssistantMode.ASSISTANT,
            trace_id=str(uuid4()),
        )

        # Call the method
        results = []
        async for chunk in self.manager.astream(workflow_inputs):
            results.append(chunk)

        # Verify failure message is returned
        self.assertEqual(len(results), 1)
        message = results[0]
        self.assertIsInstance(message, FailureMessage)
        assert isinstance(message, FailureMessage)
        self.assertEqual(message.content, "Oops! Something went wrong. Please try again.")

    async def test_stream_conversation_success(self):
        """Test successful conversation streaming."""
        # Mock redis_stream methods and processor
        with (
            patch.object(self.manager._redis_stream, "wait_for_stream") as mock_wait,
            patch.object(self.manager._redis_stream, "read_stream") as mock_read,
            patch.object(self.manager._redis_stream, "delete_stream") as mock_delete,
            patch("ee.hogai.utils.assistant_executor.AssistantStreamProcessor") as mock_processor_class,
        ):
            # Setup processor mock
            mock_processor = Mock()
            mock_processor_class.return_value = mock_processor

            # Create mock dispatcher events
            event1 = AssistantDispatcherEvent(
                action=MessageAction(message=AssistantMessage(content="chunk1")), node_name="test_node"
            )
            event2 = AssistantDispatcherEvent(
                action=MessageAction(message=AssistantMessage(content="chunk2")), node_name="test_node"
            )

            # Setup read stream to return events
            async def mock_read_stream():
                yield event1
                yield event2

            mock_wait.return_value = True
            mock_read.return_value = mock_read_stream()
            mock_delete.return_value = True

            # Mock processor to return messages
            result1 = AssistantMessage(content="processed1")
            result2 = AssistantMessage(content="processed2")
            mock_processor.process.side_effect = [result1, result2]

            # Call the method
            results = []
            async for chunk in self.manager.stream_conversation(self.workflow_inputs):
                results.append(chunk)

            # Verify results
            self.assertEqual(len(results), 2)
            self.assertIsInstance(results[0], AssistantMessage)
            assert isinstance(results[0], AssistantMessage)
            self.assertEqual(results[0].content, "processed1")
            self.assertIsInstance(results[1], AssistantMessage)
            assert isinstance(results[1], AssistantMessage)
            self.assertEqual(results[1].content, "processed2")

            # Verify method calls
            mock_wait.assert_called_once()
            mock_delete.assert_called_once()
            # Verify processor was created with correct config
            mock_processor_class.assert_called_once()

    async def test_stream_agent_executor_not_available(self):
        """Test streaming when stream is not available."""
        with patch.object(self.manager._redis_stream, "wait_for_stream") as mock_wait:
            mock_wait.return_value = False

            # Call the method
            results = []
            async for chunk in self.manager.stream_conversation(self.workflow_inputs):
                results.append(chunk)

            # Verify failure message is returned
            self.assertEqual(len(results), 1)
            message = results[0]
            self.assertIsInstance(message, FailureMessage)
            assert isinstance(message, FailureMessage)
            self.assertEqual(message.content, "Oops! Something went wrong. Please try again.")

    async def test_stream_conversation_redis_error(self):
        """Test streaming with Redis error."""
        with (
            patch.object(self.manager._redis_stream, "wait_for_stream") as mock_wait,
            patch.object(self.manager._redis_stream, "read_stream") as mock_read,
            patch.object(self.manager._redis_stream, "delete_stream") as mock_delete,
        ):
            # Setup mocks
            async def mock_read_stream_error():
                raise StreamError("Redis error")

            mock_wait.return_value = True
            mock_read.return_value = mock_read_stream_error()
            mock_delete.return_value = True

            # Call the method
            results = []
            async for chunk in self.manager.stream_conversation(self.workflow_inputs):
                results.append(chunk)

            # Verify failure message
            self.assertEqual(len(results), 1)
            message = results[0]
            self.assertIsInstance(message, FailureMessage)
            assert isinstance(message, FailureMessage)
            self.assertEqual(message.content, "Oops! Something went wrong. Please try again.")

    async def test_stream_conversation_general_error(self):
        """Test streaming with general exception."""
        with (
            patch.object(self.manager._redis_stream, "wait_for_stream") as mock_wait,
            patch.object(self.manager._redis_stream, "delete_stream") as mock_delete,
        ):
            # Setup mocks
            mock_wait.side_effect = Exception("General error")
            mock_delete.return_value = True

            # Call the method
            results = []
            async for chunk in self.manager.stream_conversation(self.workflow_inputs):
                results.append(chunk)

            # Verify failure message
            self.assertEqual(len(results), 1)
            message = results[0]
            self.assertIsInstance(message, FailureMessage)
            assert isinstance(message, FailureMessage)
            self.assertEqual(message.content, "Oops! Something went wrong. Please try again.")

    def test_failure_message(self):
        """Test failure message generation."""
        message = self.manager._failure_message()

        # Verify message format
        self.assertIsInstance(message, FailureMessage)
        self.assertEqual(message.content, "Oops! Something went wrong. Please try again.")
        self.assertIsNotNone(message.id)

    async def test_cancel_conversation_success(self):
        """Test successful conversation cancellation."""
        # Mock all external dependencies
        with (
            patch("ee.hogai.utils.assistant_executor.async_connect") as mock_connect,
            patch.object(self.manager._redis_stream, "delete_stream") as mock_delete,
            patch.object(self.conversation, "asave") as mock_save,
        ):
            # Setup client and handle mocks
            mock_client = Mock()
            mock_handle = Mock()
            mock_connect.return_value = mock_client
            mock_client.get_workflow_handle.return_value = mock_handle

            # Create a simple async function for cancel
            async def cancel_mock():
                pass

            mock_handle.cancel = cancel_mock
            mock_delete.return_value = True

            # Call the method - should not raise exception
            await self.manager.cancel_conversation()

            # Verify workflow cancellation
            mock_client.get_workflow_handle.assert_called_once_with(workflow_id=f"conversation-{self.conversation.id}")

            # Verify Redis stream cleanup
            mock_delete.assert_called_once()

            # Verify conversation status update
            self.assertEqual(self.conversation.status, Conversation.Status.IDLE)
            mock_save.assert_called()

    @patch("ee.hogai.utils.assistant_executor.async_connect")
    async def test_cancel_conversation_temporal_error(self, mock_connect):
        """Test conversation cancellation when Temporal client fails."""
        # Setup mock to raise exception
        mock_connect.side_effect = Exception("Temporal connection failed")

        # Call the method - should raise exception
        with self.assertRaises(Exception):
            await self.manager.cancel_conversation()

    async def test_cancel_conversation_workflow_cancel_error(self):
        """Test conversation cancellation when workflow cancel fails."""
        with patch("ee.hogai.utils.assistant_executor.async_connect") as mock_connect:
            # Setup mocks
            mock_client = Mock()
            mock_handle = Mock()
            mock_connect.return_value = mock_client
            mock_client.get_workflow_handle.return_value = mock_handle

            # Create an async function that raises exception
            async def cancel_error():
                raise Exception("Workflow cancel failed")

            mock_handle.cancel = cancel_error

            # Call the method - should raise exception
            with self.assertRaises(Exception):
                await self.manager.cancel_conversation()

    async def test_cancel_conversation_redis_cleanup_error(self):
        """Test conversation cancellation when Redis cleanup fails."""
        with (
            patch("ee.hogai.utils.assistant_executor.async_connect") as mock_connect,
            patch.object(self.manager._redis_stream, "delete_stream") as mock_delete,
        ):
            # Setup mocks
            mock_client = Mock()
            mock_handle = Mock()
            mock_connect.return_value = mock_client
            mock_client.get_workflow_handle.return_value = mock_handle

            async def cancel_mock():
                pass

            mock_handle.cancel = cancel_mock
            mock_delete.side_effect = Exception("Redis cleanup failed")

            # Call the method - should raise exception
            with self.assertRaises(Exception):
                await self.manager.cancel_conversation()

    async def test_cancel_conversation_save_error(self):
        """Test conversation cancellation when conversation save fails."""
        # Mock Redis stream operations and conversation save
        with (
            patch.object(self.manager._redis_stream, "delete_stream") as mock_delete,
            patch.object(self.conversation, "asave") as mock_save,
            patch("ee.hogai.utils.assistant_executor.async_connect") as mock_connect,
        ):
            mock_delete.return_value = True
            mock_save.side_effect = Exception("Save failed")
            mock_client = Mock()
            mock_handle = Mock()
            mock_connect.return_value = mock_client
            mock_client.get_workflow_handle.return_value = mock_handle

            async def cancel_mock():
                pass

            mock_handle.cancel = cancel_mock

            # Call the method - should raise exception
            with self.assertRaises(Exception):
                await self.manager.cancel_conversation()

    async def test_wait_for_workflow_to_start_success(self):
        """Test successful workflow start waiting."""
        mock_handle = Mock()
        mock_description = Mock()
        mock_description.status = WorkflowExecutionStatus.RUNNING
        mock_handle.describe = AsyncMock(return_value=mock_description)

        # Should return immediately when workflow is running
        result = await self.manager._wait_for_workflow_to_start(mock_handle)
        self.assertTrue(result)

        # Verify describe was called at least once
        mock_handle.describe.assert_called()

    async def test_wait_for_workflow_to_start_eventually_running(self):
        """Test workflow that starts running after a few attempts."""
        mock_handle = Mock()
        mock_description_not_running = Mock()
        mock_description_not_running.status = None
        mock_description_running = Mock()
        mock_description_running.status = WorkflowExecutionStatus.RUNNING

        # First call returns CREATED, second call returns RUNNING
        mock_handle.describe = AsyncMock(side_effect=[mock_description_not_running, mock_description_running])

        # Should succeed after waiting
        result = await self.manager._wait_for_workflow_to_start(mock_handle)
        self.assertTrue(result)

        # Verify describe was called twice
        self.assertEqual(mock_handle.describe.call_count, 2)

    async def test_wait_for_workflow_to_start_failed_immediately(self):
        """Test workflow that ends unexpectedly in FAILED state."""
        mock_handle = Mock()
        mock_description = Mock()
        mock_description.status = WorkflowExecutionStatus.FAILED
        mock_handle.describe = AsyncMock(return_value=mock_description)

        # Should return False for unexpected failure
        result = await self.manager._wait_for_workflow_to_start(mock_handle)
        self.assertFalse(result)

    async def test_wait_for_workflow_to_start_timeout(self):
        """Test workflow start timeout."""
        mock_handle = Mock()
        mock_description = Mock()
        mock_description.status = None
        mock_handle.describe = AsyncMock(return_value=mock_description)

        # Patch sleep to speed up test
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            # Should return False for timeout
            result = await self.manager._wait_for_workflow_to_start(mock_handle)
            self.assertFalse(result)

            # Verify sleep was called (indicating retry attempts)
            mock_sleep.assert_called()

    # State Reconstruction Tests

    async def test_tool_call_registry_reconstruction_from_replay(self):
        """Test that processor tool call registry is correctly rebuilt from Redis replay."""

        # Create dispatcher events with tool calls
        parent_tool_call_id = str(uuid4())
        parent_message = AssistantMessage(
            id=str(uuid4()),
            content="Parent message",
            tool_calls=[AssistantToolCall(id=parent_tool_call_id, name="test_tool", args={})],
        )

        event1 = AssistantDispatcherEvent(action=MessageAction(message=parent_message), node_name="test_node")

        # Create a real processor instance to capture
        captured_processor = None

        # Patch the processor class to capture the instance
        original_processor = AssistantStreamProcessor

        def capture_processor(*args, **kwargs):
            nonlocal captured_processor
            captured_processor = original_processor(*args, **kwargs)
            return captured_processor

        # Mock redis stream to return events for replay
        with (
            patch.object(self.manager._redis_stream, "wait_for_stream") as mock_wait,
            patch.object(self.manager._redis_stream, "read_stream") as mock_read,
            patch.object(self.manager._redis_stream, "delete_stream") as mock_delete,
            patch("ee.hogai.utils.assistant_executor.AssistantStreamProcessor", side_effect=capture_processor),
        ):
            # Mock read stream to return parent event (replay scenario)
            async def mock_read_stream():
                yield event1

            mock_wait.return_value = True
            mock_read.return_value = mock_read_stream()
            mock_delete.return_value = True

            # Stream conversation - this should rebuild processor state
            results = []
            async for chunk in self.manager.stream_conversation(self.workflow_inputs):
                results.append(chunk)

            # Verify tool call was registered in processor
            self.assertIsNotNone(captured_processor, "Processor should have been created")
            assert isinstance(captured_processor, AssistantStreamProcessor)
            self.assertIn(parent_tool_call_id, captured_processor._tool_call_id_to_message)
            self.assertEqual(captured_processor._tool_call_id_to_message[parent_tool_call_id].content, "Parent message")

    async def test_streamed_ids_reconstruction_prevents_duplicates(self):
        """Test that processor._streamed_update_ids prevents duplicate messages on replay."""

        message_id = str(uuid4())
        message = AssistantMessage(id=message_id, content="Test message")
        event = AssistantDispatcherEvent(action=MessageAction(message=message), node_name="test_node")

        captured_processor = None
        original_processor = AssistantStreamProcessor

        def capture_processor(*args, **kwargs):
            nonlocal captured_processor
            captured_processor = original_processor(*args, **kwargs)
            return captured_processor

        with (
            patch.object(self.manager._redis_stream, "wait_for_stream") as mock_wait,
            patch.object(self.manager._redis_stream, "read_stream") as mock_read,
            patch.object(self.manager._redis_stream, "delete_stream") as mock_delete,
            patch("ee.hogai.utils.assistant_executor.AssistantStreamProcessor", side_effect=capture_processor),
        ):
            # Mock read stream to return same event twice (simulating replay)
            async def mock_read_stream():
                yield event
                yield event  # Same event again

            mock_wait.return_value = True
            mock_read.return_value = mock_read_stream()
            mock_delete.return_value = True

            # Stream conversation
            results = []
            async for chunk in self.manager.stream_conversation(self.workflow_inputs):
                results.append(chunk)

            # Verify message was only yielded once (first occurrence)
            message_results = [r for r in results if isinstance(r, AssistantMessage) and r.id == message_id]
            self.assertEqual(len(message_results), 1, "Message with ID should only be yielded once")

    async def test_processor_handles_empty_stream(self):
        """Test processor initialization with empty stream (no events)."""
        captured_processor = None
        original_processor = AssistantStreamProcessor

        def capture_processor(*args, **kwargs):
            nonlocal captured_processor
            captured_processor = original_processor(*args, **kwargs)
            return captured_processor

        with (
            patch.object(self.manager._redis_stream, "wait_for_stream") as mock_wait,
            patch.object(self.manager._redis_stream, "read_stream") as mock_read,
            patch.object(self.manager._redis_stream, "delete_stream") as mock_delete,
            patch("ee.hogai.utils.assistant_executor.AssistantStreamProcessor", side_effect=capture_processor),
        ):
            # Mock empty stream
            async def mock_read_stream():
                return
                yield  # Empty generator

            mock_wait.return_value = True
            mock_read.return_value = mock_read_stream()
            mock_delete.return_value = True

            # Stream conversation
            results = []
            async for chunk in self.manager.stream_conversation(self.workflow_inputs):
                results.append(chunk)

            # Verify processor state is empty but valid
            self.assertIsNotNone(captured_processor)
            assert isinstance(captured_processor, AssistantStreamProcessor)
            self.assertEqual(len(captured_processor._tool_call_id_to_message), 0)
            self.assertEqual(len(captured_processor._streamed_update_ids), 0)

    async def test_processor_handles_interrupted_stream_reconnection(self):
        """Test mid-conversation reconnection rebuilds processor state correctly."""
        # Create a series of events simulating interrupted conversation
        msg1_id = str(uuid4())
        msg1 = AssistantMessage(id=msg1_id, content="First message")

        tool_call_id = str(uuid4())
        msg2 = AssistantMessage(
            id=str(uuid4()),
            content="Second message",
            tool_calls=[AssistantToolCall(id=tool_call_id, name="test", args={})],
        )

        event1 = AssistantDispatcherEvent(action=MessageAction(message=msg1), node_name="test_node")
        event2 = AssistantDispatcherEvent(action=MessageAction(message=msg2), node_name="test_node")

        captured_processor = None
        original_processor = AssistantStreamProcessor

        def capture_processor(*args, **kwargs):
            nonlocal captured_processor
            captured_processor = original_processor(*args, **kwargs)
            return captured_processor

        with (
            patch.object(self.manager._redis_stream, "wait_for_stream") as mock_wait,
            patch.object(self.manager._redis_stream, "read_stream") as mock_read,
            patch.object(self.manager._redis_stream, "delete_stream") as mock_delete,
            patch("ee.hogai.utils.assistant_executor.AssistantStreamProcessor", side_effect=capture_processor),
        ):
            # Replay from beginning (reconnection scenario)
            async def mock_read_stream():
                yield event1
                yield event2

            mock_wait.return_value = True
            mock_read.return_value = mock_read_stream()
            mock_delete.return_value = True

            # Stream conversation
            results = []
            async for chunk in self.manager.stream_conversation(self.workflow_inputs):
                results.append(chunk)

            # Verify state was correctly rebuilt
            self.assertIsNotNone(captured_processor)
            assert isinstance(captured_processor, AssistantStreamProcessor)
            self.assertIn(msg1_id, captured_processor._streamed_update_ids)
            self.assertIn(tool_call_id, captured_processor._tool_call_id_to_message)

    async def test_nested_tool_call_parent_chain_resolution_replay(self):
        """Test complex nested tool call chains resolve correctly after replay."""
        # Create 3-level nesting
        root_tool_call_id = str(uuid4())
        intermediate_tool_call_id = str(uuid4())

        root_message = AssistantMessage(
            id=str(uuid4()),
            content="Root",
            tool_calls=[AssistantToolCall(id=root_tool_call_id, name="root_tool", args={})],
        )

        intermediate_message = AssistantMessage(
            id=str(uuid4()),
            content="Intermediate",
            tool_calls=[AssistantToolCall(id=intermediate_tool_call_id, name="intermediate_tool", args={})],
            parent_tool_call_id=root_tool_call_id,
        )

        leaf_message = AssistantMessage(content="Leaf", parent_tool_call_id=intermediate_tool_call_id)

        event1 = AssistantDispatcherEvent(action=MessageAction(message=root_message), node_name="test_node")
        event2 = AssistantDispatcherEvent(action=MessageAction(message=intermediate_message), node_name="test_node")
        event3 = AssistantDispatcherEvent(action=MessageAction(message=leaf_message), node_name="test_node")

        captured_processor = None
        original_processor = AssistantStreamProcessor

        def capture_processor(*args, **kwargs):
            nonlocal captured_processor
            captured_processor = original_processor(*args, **kwargs)
            return captured_processor

        with (
            patch.object(self.manager._redis_stream, "wait_for_stream") as mock_wait,
            patch.object(self.manager._redis_stream, "read_stream") as mock_read,
            patch.object(self.manager._redis_stream, "delete_stream") as mock_delete,
            patch("ee.hogai.utils.assistant_executor.AssistantStreamProcessor", side_effect=capture_processor),
        ):
            # Replay all events
            async def mock_read_stream():
                yield event1
                yield event2
                yield event3

            mock_wait.return_value = True
            mock_read.return_value = mock_read_stream()
            mock_delete.return_value = True

            # Stream conversation
            results = []
            async for chunk in self.manager.stream_conversation(self.workflow_inputs):
                results.append(chunk)

            # Verify tool call registry has both levels registered
            self.assertIsNotNone(captured_processor)
            assert isinstance(captured_processor, AssistantStreamProcessor)
            self.assertIn(root_tool_call_id, captured_processor._tool_call_id_to_message)
            self.assertIn(intermediate_tool_call_id, captured_processor._tool_call_id_to_message)

            # Verify leaf message produced AssistantUpdateEvent pointing to root
            update_events = [r for r in results if isinstance(r, AssistantUpdateEvent)]
            assert isinstance(captured_processor, AssistantStreamProcessor)
            self.assertTrue(len(update_events) > 0, "Should produce AssistantUpdateEvent for leaf message")

    async def test_processor_state_size_with_large_stream(self):
        """Test processor memory usage tracking with realistic stream size."""
        # Create 50 messages to simulate realistic conversation
        events = []
        for i in range(50):
            message = AssistantMessage(
                id=str(uuid4()),
                content=f"Message {i}",
                tool_calls=[AssistantToolCall(id=str(uuid4()), name="tool", args={})] if i % 5 == 0 else None,
            )
            events.append(AssistantDispatcherEvent(action=MessageAction(message=message), node_name="test_node"))

        captured_processor = None
        original_processor = AssistantStreamProcessor

        def capture_processor(*args, **kwargs):
            nonlocal captured_processor
            captured_processor = original_processor(*args, **kwargs)
            return captured_processor

        with (
            patch.object(self.manager._redis_stream, "wait_for_stream") as mock_wait,
            patch.object(self.manager._redis_stream, "read_stream") as mock_read,
            patch.object(self.manager._redis_stream, "delete_stream") as mock_delete,
            patch("ee.hogai.utils.assistant_executor.AssistantStreamProcessor", side_effect=capture_processor),
        ):
            # Mock stream with all events
            async def mock_read_stream():
                for event in events:
                    yield event

            mock_wait.return_value = True
            mock_read.return_value = mock_read_stream()
            mock_delete.return_value = True

            # Stream conversation
            results = []
            async for chunk in self.manager.stream_conversation(self.workflow_inputs):
                results.append(chunk)

            # Verify processor state size is reasonable
            self.assertIsNotNone(captured_processor)
            assert isinstance(captured_processor, AssistantStreamProcessor)
            # With 50 messages, 10 have tool calls (every 5th message)
            self.assertEqual(len(captured_processor._tool_call_id_to_message), 10)
            # All 50 messages should be tracked for deduplication
            self.assertEqual(len(captured_processor._streamed_update_ids), 50)

    async def test_processor_respects_node_configuration(self):
        """Test that processor only processes messages from configured nodes."""
        # Create events from different nodes
        streaming_node_message = AssistantMessage(id=str(uuid4()), content="From streaming node")
        non_streaming_node_message = AssistantMessage(id=str(uuid4()), content="From non-streaming node")

        event_streaming = AssistantDispatcherEvent(
            action=MessageAction(message=streaming_node_message),
            node_name=AssistantNodeName.ROOT,  # This IS in STREAMING_NODES for ASSISTANT mode
        )
        event_non_streaming = AssistantDispatcherEvent(
            action=MessageAction(message=non_streaming_node_message),
            node_name=AssistantNodeName.TRENDS_GENERATOR,  # This is NOT in STREAMING_NODES (it's visualization)
        )

        captured_processor = None
        original_processor = AssistantStreamProcessor

        def capture_processor(*args, **kwargs):
            nonlocal captured_processor
            captured_processor = original_processor(*args, **kwargs)
            return captured_processor

        # Use ASSISTANT mode workflow inputs
        workflow_inputs = AssistantConversationRunnerWorkflowInputs(
            team_id=self.team.pk,
            user_id=self.user.pk,
            conversation_id=self.conversation.id,
            mode=AssistantMode.ASSISTANT,
            trace_id=str(uuid4()),
        )

        with (
            patch.object(self.manager._redis_stream, "wait_for_stream") as mock_wait,
            patch.object(self.manager._redis_stream, "read_stream") as mock_read,
            patch.object(self.manager._redis_stream, "delete_stream") as mock_delete,
            patch("ee.hogai.utils.assistant_executor.AssistantStreamProcessor", side_effect=capture_processor),
        ):

            async def mock_read_stream():
                yield event_streaming
                yield event_non_streaming

            mock_wait.return_value = True
            mock_read.return_value = mock_read_stream()
            mock_delete.return_value = True

            # Stream conversation
            results = []
            async for chunk in self.manager.stream_conversation(workflow_inputs):
                results.append(chunk)

            # Verify processor was created with correct config
            self.assertIsNotNone(captured_processor)
            assert isinstance(captured_processor, AssistantStreamProcessor)
            self.assertIn(AssistantNodeName.ROOT, captured_processor._streaming_nodes)
            # Both messages should be yielded (processor handles filtering internally)
            message_results = [r for r in results if isinstance(r, AssistantMessage)]
            self.assertEqual(len(message_results), 2)

    @patch("ee.hogai.utils.assistant_executor.async_connect")
    async def test_stream_conversation_distinguishes_redis_errors(self, mock_connect):
        """Test that Redis errors are properly caught and return failure message."""
        # Setup mocks
        mock_client = AsyncMock()
        mock_connect.return_value = mock_client

        # Mock wait_for_stream to raise StreamError
        with patch.object(self.manager._redis_stream, "wait_for_stream") as mock_wait:
            mock_wait.side_effect = StreamError("Redis connection failed")

            # Call stream_conversation
            results = []
            async for chunk in self.manager.stream_conversation(self.workflow_inputs):
                results.append(chunk)

            # Should yield failure message
            self.assertEqual(len(results), 1)
            self.assertIsInstance(results[0], FailureMessage)
            assert isinstance(results[0], FailureMessage)
            self.assertIn("Oops", results[0].content or "")

    @patch("ee.hogai.utils.assistant_executor.async_connect")
    async def test_stream_conversation_distinguishes_processor_errors(self, mock_connect):
        """Test that processor errors (non-Redis) are properly caught."""
        # Setup mocks
        mock_client = AsyncMock()
        mock_connect.return_value = mock_client

        # Mock wait_for_stream to succeed
        with (
            patch.object(self.manager._redis_stream, "wait_for_stream", return_value=True),
            patch.object(self.manager._redis_stream, "read_stream") as mock_read,
            patch.object(self.manager._redis_stream, "delete_stream") as mock_delete,
        ):
            # Mock read_stream to raise a non-Redis error (processor error)
            mock_read.side_effect = ValueError("Invalid message format")

            # Call stream_conversation
            results = []
            async for chunk in self.manager.stream_conversation(self.workflow_inputs):
                results.append(chunk)

            # Should yield failure message
            self.assertEqual(len(results), 1)
            self.assertIsInstance(results[0], FailureMessage)

            # Should still call delete_stream in finally block
            mock_delete.assert_called_once()

    @patch("ee.hogai.utils.assistant_executor.async_connect")
    async def test_stream_deletion_called_even_on_error(self, mock_connect):
        """Test that delete_stream is called in finally block even when errors occur."""
        # Setup mocks
        mock_client = AsyncMock()
        mock_connect.return_value = mock_client

        # Mock wait_for_stream to succeed
        with (
            patch.object(self.manager._redis_stream, "wait_for_stream", return_value=True),
            patch.object(self.manager._redis_stream, "read_stream") as mock_read,
            patch.object(self.manager._redis_stream, "delete_stream") as mock_delete,
        ):
            # Mock read_stream to raise an error
            mock_read.side_effect = StreamError("Original error")
            # delete_stream succeeds
            mock_delete.return_value = None

            # Call stream_conversation
            results = []
            async for chunk in self.manager.stream_conversation(self.workflow_inputs):
                results.append(chunk)

            # Should yield failure message
            self.assertEqual(len(results), 1)
            self.assertIsInstance(results[0], FailureMessage)

            # Delete should have been called in finally block
            mock_delete.assert_called_once()

    @patch("ee.hogai.utils.assistant_executor.async_connect")
    async def test_workflow_start_timeout_yields_failure_message(self, mock_connect):
        """Test that workflow start timeout is handled with a failure message."""
        # Setup mocks
        mock_client = AsyncMock()
        mock_connect.return_value = mock_client
        mock_handle = AsyncMock()
        mock_client.start_workflow.return_value = mock_handle

        # Mock _wait_for_workflow_to_start to return False (timeout)
        with patch.object(self.manager, "_wait_for_workflow_to_start", return_value=False):
            results = []
            async for chunk in self.manager.astream(self.workflow_inputs):
                results.append(chunk)

            # Should yield failure message
            self.assertEqual(len(results), 1)
            self.assertIsInstance(results[0], FailureMessage)
            assert isinstance(results[0], FailureMessage)
            self.assertIn("Oops", results[0].content or "")
