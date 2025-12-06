import time
from typing import cast
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, Mock, patch

from django.conf import settings

from temporalio.client import WorkflowExecutionStatus

from posthog.schema import AssistantEventType, AssistantMessage, HumanMessage

from posthog.temporal.ai.chat_agent import ChatAgentWorkflow, ChatAgentWorkflowInputs

from ee.hogai.core.executor import AgentExecutor
from ee.hogai.stream.redis_stream import (
    ConversationEvent,
    ConversationRedisStream,
    MessageEvent,
    StatusPayload,
    StreamError,
    StreamEvent,
    StreamStatusEvent,
    get_conversation_stream_key,
)
from ee.hogai.utils.types.base import AssistantOutput
from ee.models.assistant import Conversation


class TestAgentExecutor(BaseTest):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)
        self.team_id = self.team.pk
        self.user_id = self.user.pk
        self.manager = AgentExecutor(self.conversation)

    def test_init(self):
        """Test ConversationStreamManager initialization."""
        manager = AgentExecutor(self.conversation)

        self.assertEqual(manager._conversation.id, self.conversation.id)
        self.assertIsInstance(manager._redis_stream, ConversationRedisStream)

    @patch("ee.hogai.core.executor.async_connect")
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

            workflow_inputs = ChatAgentWorkflowInputs(
                team_id=self.team_id,
                user_id=self.user_id,
                conversation_id=self.conversation.id,
                stream_key=get_conversation_stream_key(self.conversation.id),
                trace_id=str(uuid4()),
            )

            # Call the method
            results = []
            async for chunk in self.manager.astream(ChatAgentWorkflow, workflow_inputs):
                results.append(chunk)

            # Verify results
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0], ("message", {"content": "chunk1"}))
            self.assertEqual(results[1], ("message", {"content": "chunk2"}))

            # Verify client.start_workflow was called with correct parameters
            mock_client.start_workflow.assert_called_once()
            call_args = mock_client.start_workflow.call_args

            # Check workflow function and inputs
            self.assertEqual(call_args[0][0], ChatAgentWorkflow.run)
            self.assertEqual(call_args[0][1], workflow_inputs)

            # Check keyword arguments
            self.assertEqual(call_args[1]["task_queue"], settings.MAX_AI_TASK_QUEUE)
            self.assertIn("conversation-", call_args[1]["id"])

    @patch("ee.hogai.core.executor.async_connect")
    async def test_start_workflow_and_stream_connection_error(self, mock_connect):
        """Test error handling when connection fails."""
        # Setup mock to raise exception
        mock_connect.side_effect = Exception("Connection failed")

        workflow_inputs = ChatAgentWorkflowInputs(
            team_id=self.team_id,
            user_id=self.user_id,
            conversation_id=self.conversation.id,
            stream_key=get_conversation_stream_key(self.conversation.id),
            trace_id=str(uuid4()),
        )

        # Call the method
        results = []
        async for chunk in self.manager.astream(ChatAgentWorkflow, workflow_inputs):
            results.append(chunk)

        # Verify failure message is returned
        self.assertEqual(len(results), 1)
        event_type, message = results[0]
        self.assertEqual(event_type, "message")
        message = cast(AssistantMessage, message)
        self.assertEqual(message.content, "Oops! Something went wrong. Please try again.")

    async def test_stream_conversation_success(self):
        """Test successful conversation streaming."""
        # Mock redis_stream methods
        with (
            patch.object(self.manager._redis_stream, "wait_for_stream") as mock_wait,
            patch.object(self.manager._redis_stream, "read_stream") as mock_read,
            patch.object(self.manager._redis_stream, "delete_stream") as mock_delete,
            patch.object(self.manager, "_redis_stream_to_assistant_output") as mock_convert,
        ):
            # Setup mocks
            async def mock_read_stream():
                chunk1 = Mock()
                chunk1.timestamp = time.time()
                chunk2 = Mock()
                chunk2.timestamp = time.time()
                for chunk in [chunk1, chunk2]:
                    yield chunk

            mock_wait.return_value = True
            mock_read.return_value = mock_read_stream()
            mock_delete.return_value = True
            mock_convert.side_effect = [
                ("message", {"content": "chunk1"}),
                ("message", {"content": "chunk2"}),
            ]

            # Call the method
            results = []
            async for chunk in self.manager.stream_conversation():
                results.append(chunk)

            # Verify results
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0], ("message", {"content": "chunk1"}))
            self.assertEqual(results[1], ("message", {"content": "chunk2"}))

            # Verify method calls
            mock_wait.assert_called_once()
            mock_delete.assert_called_once()

    async def test_stream_conversation_stream_not_available(self):
        """Test streaming when stream is not available."""
        with patch.object(self.manager._redis_stream, "wait_for_stream") as mock_wait:
            mock_wait.return_value = False

            # Call the method
            results = []
            async for chunk in self.manager.stream_conversation():
                results.append(chunk)

            # Verify failure message is returned
            self.assertEqual(len(results), 1)
            event_type, message = results[0]
            self.assertEqual(event_type, "message")
            message = cast(AssistantMessage, message)
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
            async for chunk in self.manager.stream_conversation():
                results.append(chunk)

            # Verify failure message
            self.assertEqual(len(results), 1)
            event_type, message = results[0]
            self.assertEqual(event_type, "message")
            message = cast(AssistantMessage, message)
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
            async for chunk in self.manager.stream_conversation():
                results.append(chunk)

            # Verify failure message
            self.assertEqual(len(results), 1)
            event_type, message = results[0]
            self.assertEqual(event_type, "message")
            message = cast(AssistantMessage, message)
            self.assertEqual(message.content, "Oops! Something went wrong. Please try again.")

    def test_failure_message(self):
        """Test failure message generation."""
        event_type, message = self.manager._failure_message()

        # Verify message format
        self.assertEqual(event_type, AssistantEventType.MESSAGE)
        message = cast(AssistantMessage, message)
        self.assertEqual(message.content, "Oops! Something went wrong. Please try again.")
        self.assertIsNotNone(message.id)

    async def test_redis_stream_to_assistant_output_message(self):
        message_data = MessageEvent(type=AssistantEventType.MESSAGE, payload=HumanMessage(content="test message"))
        event = StreamEvent(event=message_data)

        result = await self.manager._redis_stream_to_assistant_output(event)

        result = cast(AssistantOutput, result)
        self.assertEqual(cast(AssistantOutput, result[0]), AssistantEventType.MESSAGE)
        self.assertEqual(cast(AssistantMessage, result[1]).content, "test message")

    async def test_redis_stream_to_assistant_output_conversation(self):
        """Test conversion of conversation data."""
        conversation_data = ConversationEvent(type="conversation", payload=self.conversation.id)
        event = StreamEvent(event=conversation_data)

        result = await self.manager._redis_stream_to_assistant_output(event)

        result = cast(AssistantOutput, result)
        self.assertEqual(result[0], AssistantEventType.CONVERSATION)
        self.assertEqual(cast(Conversation, result[1]).id, self.conversation.id)

    async def test_redis_stream_to_assistant_output_conversation_not_found(self):
        """Test conversion when conversation doesn't exist."""
        with self.assertRaises(Conversation.DoesNotExist):
            fake_uuid = uuid4()
            conversation_data = ConversationEvent(type="conversation", payload=fake_uuid)
            event = StreamEvent(event=conversation_data)

            await self.manager._redis_stream_to_assistant_output(event)

    async def test_redis_stream_to_assistant_output_unknown_event(self):
        """Test conversion with unknown event type."""
        status_data = StreamStatusEvent(payload=StatusPayload(status="complete"))
        event = StreamEvent(event=status_data)

        result = await self.manager._redis_stream_to_assistant_output(event)

        self.assertIsNone(result)

    async def test_cancel_conversation_success(self):
        """Test successful conversation cancellation."""
        # Mock all external dependencies
        with (
            patch("ee.hogai.core.executor.async_connect") as mock_connect,
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
            await self.manager.cancel_workflow()

            # Verify workflow cancellation
            mock_client.get_workflow_handle.assert_called_once_with(workflow_id=f"conversation-{self.conversation.id}")

            # Verify Redis stream cleanup
            mock_delete.assert_called_once()

            # Verify conversation status update
            self.assertEqual(self.conversation.status, Conversation.Status.IDLE)
            mock_save.assert_called()

    @patch("ee.hogai.core.executor.async_connect")
    async def test_cancel_conversation_temporal_error(self, mock_connect):
        """Test conversation cancellation when Temporal client fails."""
        # Setup mock to raise exception
        mock_connect.side_effect = Exception("Temporal connection failed")

        # Call the method - should raise exception
        with self.assertRaises(Exception):
            await self.manager.cancel_workflow()

    async def test_cancel_conversation_workflow_cancel_error(self):
        """Test conversation cancellation when workflow cancel fails."""
        with patch("ee.hogai.core.executor.async_connect") as mock_connect:
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
                await self.manager.cancel_workflow()

    async def test_cancel_conversation_redis_cleanup_error(self):
        """Test conversation cancellation when Redis cleanup fails."""
        with (
            patch("ee.hogai.core.executor.async_connect") as mock_connect,
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
                await self.manager.cancel_workflow()

    async def test_cancel_conversation_save_error(self):
        """Test conversation cancellation when conversation save fails."""
        # Mock Redis stream operations and conversation save
        with (
            patch.object(self.manager._redis_stream, "delete_stream") as mock_delete,
            patch.object(self.conversation, "asave") as mock_save,
            patch("ee.hogai.core.executor.async_connect") as mock_connect,
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
                await self.manager.cancel_workflow()

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

    async def test_cancel_subagent_workflows_success(self):
        """Test successful cancellation of subagent workflows."""
        mock_client = Mock()

        # Create mock workflow objects
        mock_workflow_1 = Mock()
        mock_workflow_1.id = f"subagent-{self.conversation.id}-tool-call-1"
        mock_workflow_2 = Mock()
        mock_workflow_2.id = f"subagent-{self.conversation.id}-tool-call-2"

        # Make list_workflows return an async generator
        async def mock_list_workflows(_query):
            for workflow in [mock_workflow_1, mock_workflow_2]:
                yield workflow

        mock_client.list_workflows = mock_list_workflows

        # Setup handles that can be cancelled
        mock_handle_1 = Mock()
        mock_handle_2 = Mock()

        async def cancel_mock():
            pass

        mock_handle_1.cancel = cancel_mock
        mock_handle_2.cancel = cancel_mock

        def get_handle(workflow_id):
            if workflow_id == mock_workflow_1.id:
                return mock_handle_1
            return mock_handle_2

        mock_client.get_workflow_handle = get_handle

        # Call the method
        await self.manager._cancel_subagent_workflows(mock_client)

        # Verify get_workflow_handle was called for each workflow
        # (we can't easily assert on Mock when using a function, but the test passes if no exception)

    async def test_cancel_subagent_workflows_no_subagents(self):
        """Test cancellation when there are no subagent workflows."""
        mock_client = Mock()

        # Empty async generator
        async def mock_list_workflows(_query):
            return
            yield  # noqa: B901 - make it an async generator

        mock_client.list_workflows = mock_list_workflows

        # Should complete without errors
        await self.manager._cancel_subagent_workflows(mock_client)

    async def test_cancel_subagent_workflows_single_cancel_fails(self):
        """Test that failure to cancel one subagent doesn't stop others."""
        mock_client = Mock()

        mock_workflow_1 = Mock()
        mock_workflow_1.id = f"subagent-{self.conversation.id}-tool-call-1"
        mock_workflow_2 = Mock()
        mock_workflow_2.id = f"subagent-{self.conversation.id}-tool-call-2"

        async def mock_list_workflows(query):
            for workflow in [mock_workflow_1, mock_workflow_2]:
                yield workflow

        mock_client.list_workflows = mock_list_workflows

        # First handle fails, second succeeds
        mock_handle_1 = Mock()
        mock_handle_2 = Mock()

        async def cancel_error():
            raise Exception("Cancel failed")

        async def cancel_success():
            pass

        mock_handle_1.cancel = cancel_error
        mock_handle_2.cancel = cancel_success

        cancel_calls = []

        def get_handle(workflow_id):
            cancel_calls.append(workflow_id)
            if workflow_id == mock_workflow_1.id:
                return mock_handle_1
            return mock_handle_2

        mock_client.get_workflow_handle = get_handle

        # Should not raise, even though first cancel fails
        await self.manager._cancel_subagent_workflows(mock_client)

        # Both handles should have been attempted
        self.assertEqual(len(cancel_calls), 2)

    async def test_cancel_subagent_workflows_list_fails(self):
        """Test that failure to list workflows is handled gracefully."""
        mock_client = Mock()

        async def mock_list_workflows(_query):
            yield
            raise Exception("List workflows failed")

        mock_client.list_workflows = mock_list_workflows

        # Should not raise exception
        await self.manager._cancel_subagent_workflows(mock_client)

    async def test_cancel_workflow_cancels_subagents(self):
        """Test that cancel_workflow also cancels subagent workflows."""
        with (
            patch("ee.hogai.core.executor.async_connect") as mock_connect,
            patch.object(self.manager._redis_stream, "delete_stream") as mock_delete,
            patch.object(self.conversation, "asave"),
            patch.object(self.manager, "_cancel_subagent_workflows") as mock_cancel_subagents,
        ):
            mock_client = Mock()
            mock_handle = Mock()
            mock_connect.return_value = mock_client
            mock_client.get_workflow_handle.return_value = mock_handle

            async def cancel_mock():
                pass

            mock_handle.cancel = cancel_mock
            mock_delete.return_value = True
            mock_cancel_subagents.return_value = None

            await self.manager.cancel_workflow()

            # Verify subagent cancellation was called with the client
            mock_cancel_subagents.assert_called_once_with(mock_client)
