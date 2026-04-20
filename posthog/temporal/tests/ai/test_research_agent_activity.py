from uuid import uuid4

import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from posthog.temporal.ai.research_agent import ResearchAgentWorkflowInputs, process_research_agent_activity

from ee.hogai.stream.redis_stream import CONVERSATION_STREAM_PREFIX
from ee.models import Conversation


def get_research_agent_stream_key(conversation_id):
    return f"{CONVERSATION_STREAM_PREFIX}research:{conversation_id}"


@pytest.mark.django_db(transaction=True)
class TestProcessResearchAgentActivity:
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
                ("run_id", {"type": "ai", "content": "Hello", "id": "1"}),
                ("run_id", {"type": "ai", "content": " world", "id": "1"}),
                ("run_id", {"type": "ai", "content": "!", "id": "1"}),
            ]
            for chunk in chunks:
                yield chunk

        assistant.astream = mock_astream
        return assistant

    @pytest.fixture
    def research_agent_inputs(self, team, user, conversation):
        return ResearchAgentWorkflowInputs(
            team_id=team.id,
            user_id=user.id,
            conversation_id=conversation.id,
            message={"content": "Research this topic", "type": "human"},
            is_new_conversation=True,
            trace_id="test-trace",
            stream_key=get_research_agent_stream_key(conversation.id),
        )

    @pytest.mark.asyncio
    async def test_activity_success_writes_to_stream(
        self,
        research_agent_inputs,
        mock_redis_stream,
        mock_assistant,
    ):
        with (
            patch(
                "posthog.temporal.ai.research_agent.ConversationRedisStream", return_value=mock_redis_stream
            ) as mock_redis_stream_class,
            patch("posthog.temporal.ai.research_agent.ResearchAgentRunner", return_value=mock_assistant),
        ):
            await process_research_agent_activity(research_agent_inputs)

            mock_redis_stream_class.assert_called_once_with(research_agent_inputs.stream_key)
            mock_redis_stream.write_to_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_activity_retrieves_team_user_conversation_from_db(
        self,
        team,
        user,
        conversation,
        research_agent_inputs,
        mock_redis_stream,
        mock_assistant,
    ):
        with (
            patch("posthog.temporal.ai.research_agent.ConversationRedisStream", return_value=mock_redis_stream),
            patch(
                "posthog.temporal.ai.research_agent.ResearchAgentRunner", return_value=mock_assistant
            ) as mock_runner_class,
        ):
            await process_research_agent_activity(research_agent_inputs)

            mock_runner_class.assert_called_once()
            call_args = mock_runner_class.call_args

            # Verify team, conversation, and user were retrieved from DB
            assert call_args[0][0].id == team.id
            assert call_args[0][1].id == conversation.id
            assert call_args[1]["user"].id == user.id

    @pytest.mark.asyncio
    async def test_activity_initializes_runner_with_correct_params(
        self,
        team,
        user,
        conversation,
        mock_redis_stream,
        mock_assistant,
    ):
        inputs = ResearchAgentWorkflowInputs(
            team_id=team.id,
            user_id=user.id,
            conversation_id=conversation.id,
            message={"content": "Research this", "type": "human"},
            is_new_conversation=True,
            trace_id="test-trace-123",
            session_id="test-session-456",
            stream_key=get_research_agent_stream_key(conversation.id),
        )

        with (
            patch("posthog.temporal.ai.research_agent.ConversationRedisStream", return_value=mock_redis_stream),
            patch(
                "posthog.temporal.ai.research_agent.ResearchAgentRunner", return_value=mock_assistant
            ) as mock_runner_class,
        ):
            await process_research_agent_activity(inputs)

            call_kwargs = mock_runner_class.call_args[1]
            assert call_kwargs["is_new_conversation"] is True
            assert call_kwargs["trace_id"] == "test-trace-123"
            assert call_kwargs["session_id"] == "test-session-456"

    @pytest.mark.asyncio
    async def test_activity_handles_stream_error(
        self,
        research_agent_inputs,
        mock_redis_stream,
    ):
        mock_assistant = MagicMock()

        async def mock_astream():
            yield ("run_id", {"type": "ai", "content": "Hello", "id": "1"})
            raise Exception("Streaming error")

        mock_assistant.astream = mock_astream
        mock_redis_stream.write_to_stream = AsyncMock(side_effect=Exception("Streaming error"))

        with (
            patch("posthog.temporal.ai.research_agent.ConversationRedisStream", return_value=mock_redis_stream),
            patch("posthog.temporal.ai.research_agent.ResearchAgentRunner", return_value=mock_assistant),
        ):
            with pytest.raises(Exception, match="Streaming error"):
                await process_research_agent_activity(research_agent_inputs)

            mock_redis_stream.write_to_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_activity_handles_missing_message(
        self,
        team,
        user,
        conversation,
        mock_redis_stream,
        mock_assistant,
    ):
        inputs = ResearchAgentWorkflowInputs(
            team_id=team.id,
            user_id=user.id,
            conversation_id=conversation.id,
            message=None,
            stream_key=get_research_agent_stream_key(conversation.id),
        )

        with (
            patch("posthog.temporal.ai.research_agent.ConversationRedisStream", return_value=mock_redis_stream),
            patch(
                "posthog.temporal.ai.research_agent.ResearchAgentRunner", return_value=mock_assistant
            ) as mock_runner_class,
        ):
            await process_research_agent_activity(inputs)

            call_kwargs = mock_runner_class.call_args[1]
            assert call_kwargs["new_message"] is None

    @pytest.mark.asyncio
    async def test_activity_forwards_billing_context(
        self,
        team,
        user,
        conversation,
        mock_redis_stream,
        mock_assistant,
    ):
        from posthog.schema import MaxBillingContext, MaxBillingContextSettings, MaxBillingContextSubscriptionLevel

        billing_context = MaxBillingContext(
            subscription_level=MaxBillingContextSubscriptionLevel.PAID,
            has_active_subscription=True,
            products=[],
            settings=MaxBillingContextSettings(autocapture_on=True, active_destinations=0),
        )

        inputs = ResearchAgentWorkflowInputs(
            team_id=team.id,
            user_id=user.id,
            conversation_id=conversation.id,
            message={"content": "Research", "type": "human"},
            billing_context=billing_context,
            stream_key=get_research_agent_stream_key(conversation.id),
        )

        with (
            patch("posthog.temporal.ai.research_agent.ConversationRedisStream", return_value=mock_redis_stream),
            patch(
                "posthog.temporal.ai.research_agent.ResearchAgentRunner", return_value=mock_assistant
            ) as mock_runner_class,
        ):
            await process_research_agent_activity(inputs)

            call_kwargs = mock_runner_class.call_args[1]
            assert call_kwargs["billing_context"] == billing_context

    @pytest.mark.asyncio
    async def test_activity_forwards_trace_id_and_session_id(
        self,
        team,
        user,
        conversation,
        mock_redis_stream,
        mock_assistant,
    ):
        inputs = ResearchAgentWorkflowInputs(
            team_id=team.id,
            user_id=user.id,
            conversation_id=conversation.id,
            message={"content": "Research", "type": "human"},
            trace_id="custom-trace-id",
            session_id="custom-session-id",
            stream_key=get_research_agent_stream_key(conversation.id),
        )

        with (
            patch("posthog.temporal.ai.research_agent.ConversationRedisStream", return_value=mock_redis_stream),
            patch(
                "posthog.temporal.ai.research_agent.ResearchAgentRunner", return_value=mock_assistant
            ) as mock_runner_class,
        ):
            await process_research_agent_activity(inputs)

            call_kwargs = mock_runner_class.call_args[1]
            assert call_kwargs["trace_id"] == "custom-trace-id"
            assert call_kwargs["session_id"] == "custom-session-id"

    @pytest.mark.asyncio
    async def test_activity_uses_heartbeat_callback(
        self,
        research_agent_inputs,
        mock_redis_stream,
        mock_assistant,
    ):
        mock_activity = Mock()
        mock_activity.heartbeat = Mock()

        with (
            patch("posthog.temporal.ai.research_agent.ConversationRedisStream", return_value=mock_redis_stream),
            patch("posthog.temporal.ai.research_agent.ResearchAgentRunner", return_value=mock_assistant),
            patch("posthog.temporal.ai.research_agent.activity", mock_activity),
        ):
            await process_research_agent_activity(research_agent_inputs)

            # Verify write_to_stream was called with a heartbeat callback
            write_call = mock_redis_stream.write_to_stream.call_args
            assert write_call[0][1] == mock_activity.heartbeat

    @pytest.mark.asyncio
    async def test_activity_forwards_is_agent_billable(
        self,
        team,
        user,
        conversation,
        mock_redis_stream,
        mock_assistant,
    ):
        inputs = ResearchAgentWorkflowInputs(
            team_id=team.id,
            user_id=user.id,
            conversation_id=conversation.id,
            message={"content": "Research", "type": "human"},
            is_agent_billable=False,
            stream_key=get_research_agent_stream_key(conversation.id),
        )

        with (
            patch("posthog.temporal.ai.research_agent.ConversationRedisStream", return_value=mock_redis_stream),
            patch(
                "posthog.temporal.ai.research_agent.ResearchAgentRunner", return_value=mock_assistant
            ) as mock_runner_class,
        ):
            await process_research_agent_activity(inputs)

            call_kwargs = mock_runner_class.call_args[1]
            assert call_kwargs["is_agent_billable"] is False


class TestResearchAgentWorkflowInputs:
    def test_inputs_with_all_fields(self):
        from posthog.schema import MaxBillingContext, MaxBillingContextSettings, MaxBillingContextSubscriptionLevel

        billing_context = MaxBillingContext(
            subscription_level=MaxBillingContextSubscriptionLevel.PAID,
            has_active_subscription=True,
            products=[],
            settings=MaxBillingContextSettings(autocapture_on=True, active_destinations=0),
        )

        inputs = ResearchAgentWorkflowInputs(
            team_id=1,
            user_id=2,
            conversation_id=uuid4(),
            message={"content": "Research", "type": "human"},
            is_new_conversation=True,
            trace_id="trace-123",
            session_id="session-456",
            billing_context=billing_context,
            is_agent_billable=True,
            stream_key="stream-key",
        )

        assert inputs.team_id == 1
        assert inputs.user_id == 2
        assert inputs.message == {"content": "Research", "type": "human"}
        assert inputs.is_new_conversation is True
        assert inputs.trace_id == "trace-123"
        assert inputs.session_id == "session-456"
        assert inputs.billing_context == billing_context
        assert inputs.is_agent_billable is True

    def test_inputs_with_minimal_fields(self):
        conversation_id = uuid4()
        inputs = ResearchAgentWorkflowInputs(
            team_id=1,
            user_id=2,
            conversation_id=conversation_id,
            stream_key="stream-key",
        )

        assert inputs.team_id == 1
        assert inputs.user_id == 2
        assert inputs.conversation_id == conversation_id
        assert inputs.message is None
        assert inputs.is_new_conversation is False
        assert inputs.trace_id is None
        assert inputs.session_id is None
        assert inputs.billing_context is None
        assert inputs.is_agent_billable is True
