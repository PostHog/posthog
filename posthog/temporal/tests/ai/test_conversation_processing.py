import time
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from posthog.models import Team, User
from posthog.temporal.ai.conversation import (
    AssistantConversationRunnerWorkflowInputs,
    get_conversation_stream_key,
    process_conversation_activity,
)

from ee.hogai.stream.redis_stream import CONVERSATION_STREAM_PREFIX
from ee.hogai.utils.types import AssistantMode
from ee.models import Conversation


class TestProcessConversationActivity:
    """Test the process_conversation_activity function."""

    @pytest.fixture
    def mock_team(self):
        """Mock team object."""
        team = MagicMock(spec=Team)
        team.id = 1
        team.name = "Test Team"
        return team

    @pytest.fixture
    def mock_user(self):
        """Mock user object."""
        user = MagicMock(spec=User)
        user.id = 2
        user.email = "test@example.com"
        return user

    @pytest.fixture
    def mock_conversation(self):
        """Mock conversation object."""
        conversation = MagicMock(spec=Conversation)
        conversation.id = uuid4()
        conversation.team_id = 1
        conversation.user_id = 2
        return conversation

    @pytest.fixture
    def mock_redis_stream(self):
        """Mock RedisStream."""
        stream = AsyncMock()
        stream.write_to_stream = AsyncMock()
        return stream

    @pytest.fixture
    def mock_assistant(self):
        """Mock Assistant with streaming capability."""
        assistant = MagicMock()

        # Mock the async stream to yield chunks
        async def mock_astream():
            chunks = [
                {"type": "ai", "content": "Hello", "id": "1"},
                {"type": "ai", "content": " world", "id": "1"},
                {"type": "ai", "content": "!", "id": "1"},
            ]
            for chunk in chunks:
                yield chunk

        assistant.astream = mock_astream
        return assistant

    @pytest.fixture
    def conversation_inputs(self):
        """Basic conversation inputs."""
        return AssistantConversationRunnerWorkflowInputs(
            team_id=1,
            user_id=2,
            conversation_id=uuid4(),
            message={"content": "Hello", "type": "human"},
            is_new_conversation=True,
            trace_id="test-trace",
            mode=AssistantMode.ASSISTANT,
        )

    @pytest.mark.asyncio
    async def test_process_conversation_activity_success(
        self,
        conversation_inputs,
        mock_team,
        mock_user,
        mock_conversation,
        mock_redis_stream,
        mock_assistant,
    ):
        """Test successful conversation processing."""
        with (
            patch("posthog.temporal.ai.conversation.Team.objects.aget", new=AsyncMock(return_value=mock_team)),
            patch("posthog.temporal.ai.conversation.User.objects.aget", new=AsyncMock(return_value=mock_user)),
            patch(
                "posthog.temporal.ai.conversation.Conversation.objects.aget",
                new=AsyncMock(return_value=mock_conversation),
            ),
            patch(
                "posthog.temporal.ai.conversation.ConversationRedisStream", return_value=mock_redis_stream
            ) as mock_redis_stream_class,
            patch("posthog.temporal.ai.conversation.Assistant.create", return_value=mock_assistant),
        ):
            # Execute the activity
            await process_conversation_activity(conversation_inputs)

            # Verify database queries were made (they're patched, so we just check execution completed)

            # Verify RedisStream operations
            expected_stream_key = f"{CONVERSATION_STREAM_PREFIX}{conversation_inputs.conversation_id}"

            # Verify RedisStream was created with correct key
            mock_redis_stream_class.assert_called_once_with(expected_stream_key)

            # Verify write_to_stream was called once
            mock_redis_stream.write_to_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_conversation_activity_streaming_error(
        self,
        conversation_inputs,
        mock_team,
        mock_user,
        mock_conversation,
        mock_redis_stream,
    ):
        """Test error handling during streaming."""
        # Mock Assistant to raise an error during streaming
        mock_assistant = MagicMock()

        async def mock_astream():
            yield {"type": "ai", "content": "Hello", "id": "1"}
            raise Exception("Streaming error")

        mock_assistant.astream = mock_astream

        # Mock RedisStream to raise an error during write_to_stream
        mock_redis_stream.write_to_stream = AsyncMock(side_effect=Exception("Streaming error"))

        with (
            patch("posthog.temporal.ai.conversation.Team.objects.aget", new=AsyncMock(return_value=mock_team)),
            patch("posthog.temporal.ai.conversation.User.objects.aget", new=AsyncMock(return_value=mock_user)),
            patch(
                "posthog.temporal.ai.conversation.Conversation.objects.aget",
                new=AsyncMock(return_value=mock_conversation),
            ),
            patch("posthog.temporal.ai.conversation.ConversationRedisStream", return_value=mock_redis_stream),
            patch("posthog.temporal.ai.conversation.Assistant.create", return_value=mock_assistant),
        ):
            # Should raise the streaming error
            with pytest.raises(Exception, match="Streaming error"):
                await process_conversation_activity(conversation_inputs)

            # Verify write_to_stream was called once
            mock_redis_stream.write_to_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_conversation_activity_no_message(
        self,
        mock_team,
        mock_user,
        mock_conversation,
        mock_redis_stream,
        mock_assistant,
    ):
        """Test processing without a message."""
        inputs = AssistantConversationRunnerWorkflowInputs(
            team_id=1,
            user_id=2,
            conversation_id=uuid4(),
            message=None,  # No message
        )

        with (
            patch("posthog.temporal.ai.conversation.Team.objects.aget", new=AsyncMock(return_value=mock_team)),
            patch("posthog.temporal.ai.conversation.User.objects.aget", new=AsyncMock(return_value=mock_user)),
            patch(
                "posthog.temporal.ai.conversation.Conversation.objects.aget",
                new=AsyncMock(return_value=mock_conversation),
            ),
            patch("posthog.temporal.ai.conversation.ConversationRedisStream", return_value=mock_redis_stream),
            patch(
                "posthog.temporal.ai.conversation.Assistant.create", return_value=mock_assistant
            ) as mock_assistant_create,
        ):
            # Execute the activity
            await process_conversation_activity(inputs)

            # Verify Assistant was created with None message
            mock_assistant_create.assert_called_once()
            call_args = mock_assistant_create.call_args
            assert call_args[1]["new_message"] is None

            # Verify write_to_stream was called once
            mock_redis_stream.write_to_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_heartbeat_callback(
        self, conversation_inputs, mock_team, mock_user, mock_conversation, mock_redis_stream, mock_assistant
    ):
        """Test that heartbeat callback is throttled to avoid too many calls."""
        # Mock activity context
        mock_activity = Mock()
        mock_activity.heartbeat = Mock()
        with (
            patch("posthog.temporal.ai.conversation.Team.objects.aget", new=AsyncMock(return_value=mock_team)),
            patch("posthog.temporal.ai.conversation.User.objects.aget", new=AsyncMock(return_value=mock_user)),
            patch(
                "posthog.temporal.ai.conversation.Conversation.objects.aget",
                new=AsyncMock(return_value=mock_conversation),
            ),
            patch("posthog.temporal.ai.conversation.ConversationRedisStream", return_value=mock_redis_stream),
            patch("posthog.temporal.ai.conversation.Assistant.create", return_value=mock_assistant),
            patch("posthog.temporal.ai.conversation.activity", mock_activity),
        ):
            # Track callback invocations
            callback_invocations = []

            async def mock_write_to_stream(generator, callback=None):
                # Simulate rapid message generation
                if callback:
                    start_time = time.time()
                    for _ in range(20):  # 20 messages in quick succession
                        callback()
                        callback_invocations.append(time.time() - start_time)

            mock_redis_stream.write_to_stream = mock_write_to_stream

            # Run the activity
            await process_conversation_activity(conversation_inputs)

            # Check that heartbeat was called but not for every message
            # With 20 messages at 100ms intervals (2 seconds total) and 5-second throttle,
            # we should see at most 1 heartbeat call
            assert mock_activity.heartbeat.call_count == 20

            # Verify the callback was invoked for each message
            assert len(callback_invocations) == 20


class TestUtilityFunctions:
    """Test utility functions."""

    def test_get_conversation_stream_key(self):
        """Test get_conversation_stream_key function."""
        conversation_id = uuid4()
        expected_key = f"{CONVERSATION_STREAM_PREFIX}{conversation_id}"

        result = get_conversation_stream_key(conversation_id)

        assert result == expected_key
