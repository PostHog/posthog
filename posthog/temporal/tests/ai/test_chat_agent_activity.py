import time
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from posthog.schema import AgentMode

from posthog.temporal.ai.chat_agent import (
    ChatAgentWorkflowInputs,
    get_conversation_stream_key,
    process_chat_agent_activity,
    process_conversation_activity,
)

from ee.hogai.stream.redis_stream import CONVERSATION_STREAM_PREFIX
from ee.models import Conversation


@pytest.mark.django_db(transaction=True)
class TestProcessChatAgentActivity:
    @pytest.fixture
    def conversation(self, team, user):
        return Conversation.objects.create(team=team, user=user)

    @pytest.fixture
    def mock_redis_stream(self):
        stream = AsyncMock()
        stream.write_to_stream = AsyncMock()
        return stream

    @pytest.fixture
    def mock_assistant(self):
        assistant = MagicMock()

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
    def conversation_inputs(self, team, user, conversation):
        """Basic conversation inputs."""
        return ChatAgentWorkflowInputs(
            team_id=team.id,
            user_id=user.id,
            conversation_id=conversation.id,
            message={"content": "Hello", "type": "human"},
            is_new_conversation=True,
            trace_id="test-trace",
            stream_key=get_conversation_stream_key(conversation.id),
        )

    @pytest.mark.asyncio
    async def test_process_conversation_activity_success(
        self,
        conversation_inputs,
        mock_redis_stream,
        mock_assistant,
    ):
        with (
            patch(
                "posthog.temporal.ai.chat_agent.ConversationRedisStream", return_value=mock_redis_stream
            ) as mock_redis_stream_class,
            patch("posthog.temporal.ai.chat_agent.ChatAgentRunner", return_value=mock_assistant),
        ):
            await process_conversation_activity(conversation_inputs)

            mock_redis_stream_class.assert_called_once_with(conversation_inputs.stream_key)
            mock_redis_stream.write_to_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_conversation_activity_streaming_error(
        self,
        conversation_inputs,
        mock_redis_stream,
    ):
        mock_assistant = MagicMock()

        async def mock_astream():
            yield {"type": "ai", "content": "Hello", "id": "1"}
            raise Exception("Streaming error")

        mock_assistant.astream = mock_astream
        mock_redis_stream.write_to_stream = AsyncMock(side_effect=Exception("Streaming error"))

        with (
            patch("posthog.temporal.ai.chat_agent.ConversationRedisStream", return_value=mock_redis_stream),
            patch("posthog.temporal.ai.chat_agent.ChatAgentRunner", return_value=mock_assistant),
        ):
            with pytest.raises(Exception, match="Streaming error"):
                await process_conversation_activity(conversation_inputs)

            mock_redis_stream.write_to_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_conversation_activity_no_message(
        self,
        team,
        user,
        conversation,
        mock_redis_stream,
        mock_assistant,
    ):
        """Test processing without a message."""
        inputs = ChatAgentWorkflowInputs(
            team_id=team.id,
            user_id=user.id,
            conversation_id=conversation.id,
            message=None,
            stream_key=get_conversation_stream_key(uuid4()),
        )

        with (
            patch("posthog.temporal.ai.chat_agent.ConversationRedisStream", return_value=mock_redis_stream),
            patch(
                "posthog.temporal.ai.chat_agent.ChatAgentRunner", return_value=mock_assistant
            ) as mock_assistant_create,
        ):
            # Execute the activity
            await process_chat_agent_activity(inputs)

            mock_assistant_create.assert_called_once()
            call_args = mock_assistant_create.call_args
            assert call_args[1]["new_message"] is None
            mock_redis_stream.write_to_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_conversation_activity_sets_agent_mode(
        self,
        team,
        user,
        conversation,
        mock_redis_stream,
        mock_assistant,
    ):
        """Ensure agent mode is forwarded to the runner."""
        inputs = ChatAgentWorkflowInputs(
            team_id=team.id,
            user_id=user.id,
            conversation_id=conversation.id,
            message={"content": "Hello", "type": "human"},
            agent_mode=AgentMode.SESSION_REPLAY,
            stream_key=get_conversation_stream_key(uuid4()),
        )

        with (
            patch("posthog.temporal.ai.chat_agent.ConversationRedisStream", return_value=mock_redis_stream),
            patch(
                "posthog.temporal.ai.chat_agent.ChatAgentRunner", return_value=mock_assistant
            ) as mock_assistant_create,
        ):
            await process_chat_agent_activity(inputs)

            assert mock_assistant_create.call_args[1]["agent_mode"] == AgentMode.SESSION_REPLAY
            mock_redis_stream.write_to_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_conversation_activity_passes_parent_span_id(
        self,
        team,
        user,
        conversation,
        mock_redis_stream,
        mock_assistant,
    ):
        """Ensure parent_span_id is forwarded to the runner for subagent tracing."""
        parent_span_id = "test-parent-span-id"
        inputs = ChatAgentWorkflowInputs(
            team_id=team.id,
            user_id=user.id,
            conversation_id=conversation.id,
            message={"content": "Hello", "type": "human"},
            parent_span_id=parent_span_id,
            stream_key=get_conversation_stream_key(uuid4()),
        )

        with (
            patch("posthog.temporal.ai.chat_agent.ConversationRedisStream", return_value=mock_redis_stream),
            patch(
                "posthog.temporal.ai.chat_agent.ChatAgentRunner", return_value=mock_assistant
            ) as mock_assistant_create,
        ):
            await process_chat_agent_activity(inputs)

            assert mock_assistant_create.call_args[1]["parent_span_id"] == parent_span_id
            mock_redis_stream.write_to_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_heartbeat_callback(self, conversation_inputs, mock_redis_stream, mock_assistant):
        mock_activity = Mock()
        mock_activity.heartbeat = Mock()
        with (
            patch("posthog.temporal.ai.chat_agent.ConversationRedisStream", return_value=mock_redis_stream),
            patch("posthog.temporal.ai.chat_agent.ChatAgentRunner", return_value=mock_assistant),
            patch("posthog.temporal.ai.chat_agent.activity", mock_activity),
        ):
            callback_invocations = []

            async def mock_write_to_stream(generator, callback=None):
                if callback:
                    start_time = time.time()
                    for _ in range(20):
                        callback()
                        callback_invocations.append(time.time() - start_time)

            mock_redis_stream.write_to_stream = mock_write_to_stream

            await process_conversation_activity(conversation_inputs)

            assert mock_activity.heartbeat.call_count == 20
            assert len(callback_invocations) == 20


class TestUtilityFunctions:
    def test_get_conversation_stream_key(self):
        conversation_id = uuid4()
        expected_key = f"{CONVERSATION_STREAM_PREFIX}{conversation_id}"

        result = get_conversation_stream_key(conversation_id)

        assert result == expected_key
