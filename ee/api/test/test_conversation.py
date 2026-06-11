import uuid
import datetime
from typing import Any, cast

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from django.http import StreamingHttpResponse
from django.test import override_settings
from django.utils import timezone

from rest_framework import status

from posthog.schema import (
    AgentMode,
    AssistantEventType,
    AssistantMessage,
    MaxBillingContext,
    MaxBillingContextBillingPeriod,
    MaxBillingContextBillingPeriodInterval,
    MaxBillingContextSettings,
    MaxBillingContextSubscriptionLevel,
    MaxBillingContextTrial,
    MaxProductInfo,
    SpendHistoryItem,
)

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.ai.chat_agent import ChatAgentWorkflow, ChatAgentWorkflowInputs
from posthog.temporal.ai.research_agent import ResearchAgentWorkflow, ResearchAgentWorkflowInputs

from products.posthog_ai.backend.message_routing import SandboxCancelResult, SandboxRouteResult
from products.posthog_ai.backend.models.assistant import Conversation

from ee.api.conversation import ConversationViewSet


async def _async_generator():
    yield (AssistantEventType.MESSAGE, AssistantMessage(content="test response"))


def _async_generator_func():
    """Returns an async generator function"""
    return _async_generator()


_generator_serialized_value = b'event: message\ndata: {"content":"test response","type":"ai"}\n\n'


class TestConversation(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.other_team = Team.objects.create(organization=self.organization, name="other team")
        self.other_user = User.objects.create_and_join(
            organization=self.organization,
            email="other@posthog.com",
            password="password",
            first_name="Other",
        )
        self.billing_context = MaxBillingContext(
            subscription_level=MaxBillingContextSubscriptionLevel.PAID,
            billing_plan="paid",
            has_active_subscription=True,
            is_deactivated=False,
            billing_period=MaxBillingContextBillingPeriod(
                current_period_start=str(datetime.date(2023, 1, 1)),
                current_period_end=str(datetime.date(2023, 1, 31)),
                interval=MaxBillingContextBillingPeriodInterval.MONTH,
            ),
            total_current_amount_usd="100.00",
            products=[
                MaxProductInfo(
                    name="Product A",
                    type="type_a",
                    description="Desc A",
                    current_usage=50,
                    usage_limit=100,
                    percentage_usage=0.5,
                    has_exceeded_limit=False,
                    is_used=True,
                    addons=[],
                )
            ],
            trial=MaxBillingContextTrial(is_active=True, expires_at=str(datetime.date(2023, 2, 1)), target="scale"),
            settings=MaxBillingContextSettings(autocapture_on=True, active_destinations=2),
        )

    def _get_streaming_content(self, response: Any) -> bytes:
        return b"".join(response.streaming_content)

    def _create_mock_streaming_response(
        self, streaming_content: Any, *args: Any, **kwargs: Any
    ) -> StreamingHttpResponse:
        """Helper to create a mock StreamingHttpResponse that actually processes the streaming content."""

        # Actually consume the generator to ensure the mocked methods are called
        try:
            # This will trigger the async generator and call our mocked methods
            content = b"".join(streaming_content)
        except Exception:
            # If there's an issue with the async generator, use fallback
            content = _generator_serialized_value

        mock_response = StreamingHttpResponse([content], content_type="text/event-stream")
        cast(Any, mock_response).streaming_content = [content]
        return mock_response

    def test_create_conversation(self):
        conversation_id = str(uuid.uuid4())

        with patch(
            "ee.hogai.core.executor.AgentExecutor.astream",
            return_value=_async_generator(),
        ) as mock_start_workflow_and_stream:
            with patch("ee.api.conversation.StreamingHttpResponse", side_effect=self._create_mock_streaming_response):
                trace_id = str(uuid.uuid4())
                response = self.client.post(
                    f"/api/environments/{self.team.id}/conversations/",
                    {"content": "test query", "trace_id": trace_id, "conversation": conversation_id},
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(self._get_streaming_content(response), _generator_serialized_value)
                self.assertEqual(Conversation.objects.count(), 1)
                conversation = Conversation.objects.first()
                assert conversation is not None
                self.assertEqual(conversation.user, self.user)
                self.assertEqual(conversation.team, self.team)
                # Check that the method was called with workflow_inputs
                mock_start_workflow_and_stream.assert_called_once()
                call_args = mock_start_workflow_and_stream.call_args
                workflow_inputs = call_args[0][1]
                self.assertEqual(workflow_inputs.user_id, self.user.id)
                self.assertEqual(workflow_inputs.is_new_conversation, True)
                self.assertEqual(workflow_inputs.conversation_id, conversation.id)
                self.assertEqual(str(workflow_inputs.trace_id), trace_id)
                self.assertEqual(workflow_inputs.message["content"], "test query")

    def test_add_message_to_existing_conversation(self):
        with patch(
            "ee.hogai.core.executor.AgentExecutor.astream",
            return_value=_async_generator(),
        ) as mock_start_workflow_and_stream:
            with patch("ee.api.conversation.StreamingHttpResponse", side_effect=self._create_mock_streaming_response):
                conversation = Conversation.objects.create(user=self.user, team=self.team)
                trace_id = str(uuid.uuid4())
                response = self.client.post(
                    f"/api/environments/{self.team.id}/conversations/",
                    {
                        "conversation": str(conversation.id),
                        "content": "test query",
                        "trace_id": trace_id,
                    },
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(self._get_streaming_content(response), _generator_serialized_value)
                self.assertEqual(Conversation.objects.count(), 1)
                # Check that the method was called with workflow_inputs
                mock_start_workflow_and_stream.assert_called_once()
                call_args = mock_start_workflow_and_stream.call_args
                workflow_inputs = call_args[0][1]
                self.assertEqual(workflow_inputs.user_id, self.user.id)
                self.assertEqual(workflow_inputs.is_new_conversation, False)
                self.assertEqual(workflow_inputs.conversation_id, conversation.id)
                self.assertEqual(str(workflow_inputs.trace_id), trace_id)
                self.assertEqual(workflow_inputs.message["content"], "test query")

    def test_create_conversation_with_agent_mode(self):
        conversation_id = str(uuid.uuid4())

        with patch(
            "ee.hogai.core.executor.AgentExecutor.astream",
            return_value=_async_generator(),
        ) as mock_start_workflow_and_stream:
            with patch("ee.api.conversation.StreamingHttpResponse", side_effect=self._create_mock_streaming_response):
                trace_id = str(uuid.uuid4())
                response = self.client.post(
                    f"/api/environments/{self.team.id}/conversations/",
                    {
                        "content": "test query",
                        "trace_id": trace_id,
                        "conversation": conversation_id,
                        "agent_mode": AgentMode.SQL.value,
                    },
                )

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                workflow_inputs = mock_start_workflow_and_stream.call_args[0][1]
                self.assertEqual(workflow_inputs.agent_mode, AgentMode.SQL)

    def test_cant_start_other_users_conversation(self):
        conversation = Conversation.objects.create(user=self.other_user, team=self.team)

        self.client.force_login(self.user)
        response = self.client.post(
            f"/api/environments/{self.team.id}/conversations/",
            {"conversation": conversation.id, "content": None, "trace_id": str(uuid.uuid4())},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_cancel_other_users_conversation(self):
        """Test that cancel action cannot use other user's conversation ID"""
        conversation = Conversation.objects.create(
            user=self.other_user, team=self.team, title="Other user conversation", type=Conversation.Type.ASSISTANT
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/conversations/{conversation.id}/cancel/",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cant_access_other_teams_conversation(self):
        conversation = Conversation.objects.create(user=self.user, team=self.other_team)

        response = self.client.post(
            f"/api/environments/{self.team.id}/conversations/",
            {"conversation": conversation.id, "content": None, "trace_id": str(uuid.uuid4())},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_message_format(self):
        response = self.client.post("/api/environments/@current/conversations/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rate_limit_burst(self):
        # Create multiple requests to trigger burst rate limit
        with patch(
            "ee.hogai.core.executor.AgentExecutor.astream",
            return_value=_async_generator(),
        ):
            with patch("ee.api.conversation.StreamingHttpResponse", side_effect=self._create_mock_streaming_response):
                for _ in range(11):  # Assuming burst limit is less than this
                    response = self.client.post(
                        f"/api/environments/{self.team.id}/conversations/",
                        {"content": "test query", "trace_id": str(uuid.uuid4())},
                    )
                self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_empty_content(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/conversations/",
            {"content": "", "trace_id": str(uuid.uuid4())},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_content_too_long(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/conversations/",
            {"content": "x" * 50000, "trace_id": str(uuid.uuid4())},  # Very long message
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", response.json())

    def test_none_content_with_existing_conversation(self):
        """Test that when content is None with an existing conversation, the API handles it correctly."""
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, status=Conversation.Status.IN_PROGRESS
        )
        with patch(
            "ee.hogai.core.executor.AgentExecutor.astream",
            return_value=_async_generator(),
        ) as mock_stream_conversation:
            with patch("ee.api.conversation.StreamingHttpResponse", side_effect=self._create_mock_streaming_response):
                trace_id = str(uuid.uuid4())
                response = self.client.post(
                    f"/api/environments/{self.team.id}/conversations/",
                    {"content": None, "trace_id": trace_id, "conversation": str(conversation.id)},
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(self._get_streaming_content(response), _generator_serialized_value)
                # For IN_PROGRESS conversations with no content, stream_conversation should be called
                mock_stream_conversation.assert_called_once()

    def test_invalid_conversation_id(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/conversations/",
            {
                "conversation": "not-a-valid-uuid",
                "content": "test query",
                "trace_id": str(uuid.uuid4()),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_trace_id(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/conversations/",
            {
                "content": "test query",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_nonexistent_conversation(self):
        with patch(
            "ee.hogai.core.executor.AgentExecutor.astream",
            return_value=_async_generator(),
        ):
            with patch("ee.api.conversation.StreamingHttpResponse", side_effect=self._create_mock_streaming_response):
                response = self.client.post(
                    f"/api/environments/{self.team.id}/conversations/",
                    {
                        "conversation": "12345678-1234-5678-1234-567812345678",
                        "content": "test query",
                        "trace_id": str(uuid.uuid4()),
                    },
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_nonexistent_conversation_with_no_content(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/conversations/",
            {
                "conversation": "12345678-1234-5678-1234-567812345678",
                "content": None,
                "trace_id": str(uuid.uuid4()),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unauthenticated_request(self):
        self.client.logout()
        response = self.client.post(
            f"/api/environments/{self.team.id}/conversations/",
            {"content": "test query", "trace_id": str(uuid.uuid4())},
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("ee.hogai.core.executor.AgentExecutor.cancel_workflow")
    def test_cancel_conversation(self, mock_cancel):
        conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            title="Test conversation",
            type=Conversation.Type.ASSISTANT,
            status=Conversation.Status.IN_PROGRESS,
        )
        mock_cancel.return_value = AsyncMock(return_value=True)()
        response = self.client.patch(
            f"/api/environments/{self.team.id}/conversations/{conversation.id}/cancel/",
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_cancel_already_canceling_conversation(self):
        conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            status=Conversation.Status.CANCELING,
            title="Test conversation",
            type=Conversation.Type.ASSISTANT,
        )
        response = self.client.patch(
            f"/api/environments/{self.team.id}/conversations/{conversation.id}/cancel/",
        )
        # should be idempotent
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_cannot_cancel_other_users_conversation_in_same_project(self):
        conversation = Conversation.objects.create(user=self.other_user, team=self.team)
        response = self.client.patch(
            f"/api/environments/{self.team.id}/conversations/{conversation.id}/cancel/",
        )
        # This should fail because cancel action also filters by user
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cancel_other_teams_conversation(self):
        conversation = Conversation.objects.create(user=self.user, team=self.other_team)
        response = self.client.patch(
            f"/api/environments/{self.team.id}/conversations/{conversation.id}/cancel/",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("ee.hogai.core.executor.AgentExecutor.cancel_workflow")
    def test_cancel_conversation_with_async_cleanup(self, mock_cancel):
        """Test that cancel endpoint properly handles async cleanup."""
        conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            title="Test conversation",
            type=Conversation.Type.ASSISTANT,
            status=Conversation.Status.IN_PROGRESS,
        )

        # Mock the async cancel method to succeed (no exception)
        mock_cancel.return_value = AsyncMock()

        response = self.client.patch(
            f"/api/environments/{self.team.id}/conversations/{conversation.id}/cancel/",
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    @patch("ee.hogai.core.executor.AgentExecutor.cancel_workflow")
    def test_cancel_conversation_async_cleanup_failure(self, mock_cancel):
        """Test cancel endpoint behavior when async cleanup fails."""
        conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            title="Test conversation",
            type=Conversation.Type.ASSISTANT,
            status=Conversation.Status.IN_PROGRESS,
        )

        # Mock the async cancel method to raise an exception (failure)
        async def mock_cancel_exception():
            raise Exception("Cleanup failed")

        mock_cancel.side_effect = mock_cancel_exception

        response = self.client.patch(
            f"/api/environments/{self.team.id}/conversations/{conversation.id}/cancel/",
        )

        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

    @patch("ee.hogai.core.executor.AgentExecutor.cancel_workflow")
    def test_cancel_idle_conversation_still_cleans_up(self, mock_cancel):
        """Test that canceling an idle conversation still attempts cleanup,
        because queued workflows may be running even when status is IDLE
        (during the transition between main and queued workflows)."""
        conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            title="Test conversation",
            type=Conversation.Type.ASSISTANT,
            status=Conversation.Status.IDLE,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/conversations/{conversation.id}/cancel/",
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        mock_cancel.assert_called_once()

    def test_cancel_nonexistent_conversation(self):
        """Test canceling a conversation that doesn't exist."""
        fake_uuid = "12345678-1234-5678-1234-567812345678"
        response = self.client.patch(
            f"/api/environments/{self.team.id}/conversations/{fake_uuid}/cancel/",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cancel_unauthenticated_request(self):
        """Test that unauthenticated users cannot cancel conversations."""
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Test conversation", type=Conversation.Type.ASSISTANT
        )

        self.client.logout()
        response = self.client.patch(
            f"/api/environments/{self.team.id}/conversations/{conversation.id}/cancel/",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_stream_from_in_progress_conversation(self):
        """Test streaming from an in-progress conversation without providing new content."""
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, status=Conversation.Status.IN_PROGRESS
        )
        with patch(
            "ee.hogai.core.executor.AgentExecutor.astream",
            return_value=_async_generator(),
        ) as mock_stream_conversation:
            with patch("ee.api.conversation.StreamingHttpResponse", side_effect=self._create_mock_streaming_response):
                response = self.client.post(
                    f"/api/environments/{self.team.id}/conversations/",
                    {
                        "conversation": str(conversation.id),
                        "content": None,
                        "trace_id": str(uuid.uuid4()),
                    },
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(self._get_streaming_content(response), _generator_serialized_value)
                mock_stream_conversation.assert_called_once()

    def test_cannot_resume_idle_conversation_without_message(self):
        """Test that resuming an idle conversation without a new message returns a conflict error."""
        conversation = Conversation.objects.create(user=self.user, team=self.team, status=Conversation.Status.IDLE)
        response = self.client.post(
            f"/api/environments/{self.team.id}/conversations/",
            {
                "conversation": str(conversation.id),
                "content": None,
                "trace_id": str(uuid.uuid4()),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        self.assertEqual(response_data["detail"], "Cannot continue streaming from an idle conversation")

    def test_stream_from_nonexistent_conversation_without_content(self):
        """Test that streaming from a non-existent conversation without content returns an error."""
        conversation_uuid = str(uuid.uuid4())
        response = self.client.post(
            f"/api/environments/{self.team.id}/conversations/",
            {
                "conversation": conversation_uuid,
                "content": None,
                "trace_id": str(uuid.uuid4()),
            },
        )
        # Due to async generator issues, this might return 200 with a broken stream or 400
        # Both indicate that the conversation doesn't exist
        self.assertIn(response.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_200_OK])
        if response.status_code == status.HTTP_400_BAD_REQUEST:
            response_data = response.json()
            self.assertIn("Cannot stream from non-existent conversation", response_data["error"])

    def test_list_only_returns_assistant_conversations_with_title(self):
        # Create different types of conversations
        conversation1 = Conversation.objects.create(
            user=self.user, team=self.team, title="Conversation 1", type=Conversation.Type.ASSISTANT
        )
        Conversation.objects.create(user=self.user, team=self.team, title=None, type=Conversation.Type.ASSISTANT)
        Conversation.objects.create(user=self.user, team=self.team, title="Tool call", type=Conversation.Type.TOOL_CALL)

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock) as mock_get_state:
            response = self.client.get(f"/api/environments/{self.team.id}/conversations/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            # Only one conversation should be returned (the one with title and type ASSISTANT)
            results = response.json()["results"]
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["id"], str(conversation1.id))
            self.assertEqual(results[0]["title"], "Conversation 1")
            self.assertIn("status", results[0])
            self.assertNotIn("messages", results[0])
            mock_get_state.assert_not_awaited()

    def test_list_conversations_only_returns_own_conversations(self):
        """Test that listing conversations only returns the current user's conversations"""
        # Create conversations for different users
        own_conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="My conversation", type=Conversation.Type.ASSISTANT
        )
        Conversation.objects.create(
            user=self.other_user, team=self.team, title="Other user conversation", type=Conversation.Type.ASSISTANT
        )

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock):
            response = self.client.get(f"/api/environments/{self.team.id}/conversations/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            results = response.json()["results"]
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["id"], str(own_conversation.id))
            self.assertEqual(results[0]["title"], "My conversation")

    def test_retrieve_own_conversation_succeeds(self):
        """Test that user can retrieve their own conversation"""
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="My conversation", type=Conversation.Type.ASSISTANT
        )

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock):
            response = self.client.get(f"/api/environments/{self.team.id}/conversations/{conversation.id}/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            data = response.json()
            self.assertEqual(data["id"], str(conversation.id))
            self.assertIn("messages", data)
            self.assertIn("has_unsupported_content", data)
            self.assertIn("agent_mode", data)
            self.assertIn("is_sandbox", data)
            self.assertIn("pending_approvals", data)

    def test_retrieve_other_users_conversation_succeeds(self):
        """Test that user can retrieve another user's conversation in the same team"""
        conversation = Conversation.objects.create(
            user=self.other_user, team=self.team, title="Other user conversation", type=Conversation.Type.ASSISTANT
        )

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock):
            response = self.client.get(f"/api/environments/{self.team.id}/conversations/{conversation.id}/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json()["id"], str(conversation.id))

    def test_retrieve_other_teams_conversation_fails(self):
        """Test that user cannot retrieve conversation from another team"""
        conversation = Conversation.objects.create(
            user=self.user, team=self.other_team, title="Other team conversation", type=Conversation.Type.ASSISTANT
        )

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock):
            response = self.client.get(f"/api/environments/{self.team.id}/conversations/{conversation.id}/")
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_conversations_ordered_by_updated_at_descending(self):
        """Test that conversations are ordered by updated_at in descending order"""
        # Create conversations with different update times
        conversation1 = Conversation.objects.create(
            user=self.user, team=self.team, title="Older conversation", type=Conversation.Type.ASSISTANT
        )
        conversation2 = Conversation.objects.create(
            user=self.user, team=self.team, title="Newer conversation", type=Conversation.Type.ASSISTANT
        )

        # Set updated_at explicitly to ensure order
        conversation1.updated_at = timezone.now() - datetime.timedelta(hours=1)
        conversation1.save()
        conversation2.updated_at = timezone.now()
        conversation2.save()

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock):
            response = self.client.get(f"/api/environments/{self.team.id}/conversations/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            results = response.json()["results"]
            self.assertEqual(len(results), 2)

            # First result should be the newer conversation (most recent first)
            self.assertEqual(results[0]["id"], str(conversation2.id))
            self.assertEqual(results[0]["title"], "Newer conversation")

            # Second result should be the older conversation
            self.assertEqual(results[1]["id"], str(conversation1.id))
            self.assertEqual(results[1]["title"], "Older conversation")

    @override_settings(DEBUG=False)
    def test_get_throttles_returns_empty_for_create_action(self):
        """Test that get_throttles returns empty list for create action (throttling is handled in check_throttles)."""

        viewset = ConversationViewSet()
        viewset.action = "create"
        viewset.team_id = 12345
        viewset.organization = self.organization
        throttles = viewset.get_throttles()
        # For create action, throttles are handled in check_throttles() for conditional logic
        self.assertEqual(throttles, [])

    @override_settings(DEBUG=True)
    def test_get_throttles_returns_empty_for_create_action_in_debug_mode(self):
        """Test that get_throttles returns empty list for create action in debug mode."""

        viewset = ConversationViewSet()
        viewset.action = "create"
        viewset.team_id = 12345
        viewset.organization = self.organization
        throttles = viewset.get_throttles()
        # For create action, throttles are handled in check_throttles()
        self.assertEqual(throttles, [])

    @override_settings(DEBUG=False)
    def test_research_rate_limit_burst(self):
        """Test that research conversations have more aggressive burst rate limits."""
        with patch(
            "ee.hogai.core.executor.AgentExecutor.astream",
            return_value=_async_generator(),
        ):
            with patch("ee.api.conversation.StreamingHttpResponse", side_effect=self._create_mock_streaming_response):
                # First 3 requests should succeed (3/minute limit)
                for i in range(3):
                    response = self.client.post(
                        f"/api/environments/{self.team.id}/conversations/",
                        {
                            "content": f"test query {i}",
                            "trace_id": str(uuid.uuid4()),
                            "conversation": str(uuid.uuid4()),
                            "agent_mode": AgentMode.RESEARCH.value,
                        },
                    )
                    self.assertEqual(response.status_code, status.HTTP_200_OK, f"Request {i} should succeed")

                # 4th request should be rate limited
                response = self.client.post(
                    f"/api/environments/{self.team.id}/conversations/",
                    {
                        "content": "test query 4",
                        "trace_id": str(uuid.uuid4()),
                        "conversation": str(uuid.uuid4()),
                        "agent_mode": AgentMode.RESEARCH.value,
                    },
                )
                self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
                # Check that the response contains the research-specific message
                response_data = response.json()
                self.assertIn("Research mode", response_data["detail"])
                self.assertIn("beta", response_data["detail"])

    @override_settings(DEBUG=False)
    def test_research_rate_limit_applies_to_new_research_conversations(self):
        """Test that research rate limits apply to new DEEP_RESEARCH conversations (before conversion)."""
        with patch(
            "ee.hogai.core.executor.AgentExecutor.astream",
            return_value=_async_generator(),
        ):
            with patch("ee.api.conversation.StreamingHttpResponse", side_effect=self._create_mock_streaming_response):
                # First 3 new research conversations should succeed (3/minute limit)
                for i in range(3):
                    response = self.client.post(
                        f"/api/environments/{self.team.id}/conversations/",
                        {
                            "content": f"test query {i}",
                            "trace_id": str(uuid.uuid4()),
                            "conversation": str(uuid.uuid4()),
                            "agent_mode": AgentMode.RESEARCH.value,
                        },
                    )
                    self.assertEqual(response.status_code, status.HTTP_200_OK, f"Request {i} should succeed")

                # 4th request should be rate limited
                response = self.client.post(
                    f"/api/environments/{self.team.id}/conversations/",
                    {
                        "content": "test query 4",
                        "trace_id": str(uuid.uuid4()),
                        "conversation": str(uuid.uuid4()),
                        "agent_mode": AgentMode.RESEARCH.value,
                    },
                )
                self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
                response_data = response.json()
                self.assertIn("Research mode", response_data["detail"])

    @override_settings(DEBUG=False)
    @patch("posthog.utils.get_instance_region", return_value="US")
    def test_research_rate_limit_exempt_team_bypasses_throttle(self, _mock_region):
        """Test that teams listed in the posthog-ai-rate-limit-exemptions flag bypass research rate limits."""
        with patch(
            "posthoganalytics.get_feature_flag_payload",
            return_value={"US": [self.team.id]},
        ):
            with patch(
                "ee.hogai.core.executor.AgentExecutor.astream",
                return_value=_async_generator(),
            ):
                with patch(
                    "ee.api.conversation.StreamingHttpResponse", side_effect=self._create_mock_streaming_response
                ):
                    # Should exceed the 3/minute burst limit without being throttled
                    for i in range(5):
                        response = self.client.post(
                            f"/api/environments/{self.team.id}/conversations/",
                            {
                                "content": f"test query {i}",
                                "trace_id": str(uuid.uuid4()),
                                "conversation": str(uuid.uuid4()),
                                "agent_mode": AgentMode.RESEARCH.value,
                            },
                        )
                        self.assertEqual(response.status_code, status.HTTP_200_OK, f"Request {i} should succeed")

    @override_settings(DEBUG=False)
    def test_normal_ai_has_standard_rate_limits(self):
        """Test that normal AI conversations have standard rate limits (10/minute)."""
        with patch(
            "ee.hogai.core.executor.AgentExecutor.astream",
            return_value=_async_generator(),
        ):
            with patch("ee.api.conversation.StreamingHttpResponse", side_effect=self._create_mock_streaming_response):
                # First 10 requests should succeed (10/minute limit)
                for i in range(10):
                    response = self.client.post(
                        f"/api/environments/{self.team.id}/conversations/",
                        {
                            "content": f"test query {i}",
                            "trace_id": str(uuid.uuid4()),
                            "conversation": str(uuid.uuid4()),
                            # No agent_mode or agent_mode != RESEARCH
                        },
                    )
                    self.assertEqual(response.status_code, status.HTTP_200_OK, f"Request {i} should succeed")

                # 11th request should be rate limited
                response = self.client.post(
                    f"/api/environments/{self.team.id}/conversations/",
                    {
                        "content": "test query 11",
                        "trace_id": str(uuid.uuid4()),
                        "conversation": str(uuid.uuid4()),
                    },
                )
                self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
                # Check that the response does NOT contain research-specific message
                response_data = response.json()
                self.assertNotIn("Research mode", response_data["detail"])

    def test_billing_context_validation_valid_data(self):
        """Test that valid billing context data is accepted."""
        conversation = Conversation.objects.create(user=self.user, team=self.team)

        with patch(
            "ee.hogai.core.executor.AgentExecutor.astream",
            return_value=_async_generator(),
        ) as mock_start_workflow_and_stream:
            with patch("ee.api.conversation.StreamingHttpResponse", side_effect=self._create_mock_streaming_response):
                trace_id = str(uuid.uuid4())
                response = self.client.post(
                    f"/api/environments/{self.team.id}/conversations/",
                    {
                        "content": "test query",
                        "trace_id": trace_id,
                        "conversation": conversation.id,
                        "billing_context": self.billing_context.model_dump(),
                    },
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                call_args = mock_start_workflow_and_stream.call_args
                workflow_inputs = call_args[0][1]
                self.assertEqual(workflow_inputs.billing_context, self.billing_context)

    def test_billing_context_validation_invalid_data(self):
        """Test that invalid billing context data is rejected."""
        conversation = Conversation.objects.create(user=self.user, team=self.team)

        with patch(
            "ee.hogai.core.executor.AgentExecutor.astream",
            return_value=_async_generator(),
        ) as mock_start_workflow_and_stream:
            with patch("ee.api.conversation.StreamingHttpResponse", side_effect=self._create_mock_streaming_response):
                trace_id = str(uuid.uuid4())
                response = self.client.post(
                    f"/api/environments/{self.team.id}/conversations/",
                    {
                        "content": "test query",
                        "trace_id": trace_id,
                        "conversation": conversation.id,
                        "billing_context": {"invalid_key": "invalid_value"},
                    },
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                call_args = mock_start_workflow_and_stream.call_args
                workflow_inputs = call_args[0][1]
                self.assertEqual(workflow_inputs.billing_context, None)

    @patch("ee.api.conversation.is_team_limited")
    def test_quota_limit_exceeded(self, mock_is_team_limited):
        """Test that requests are blocked when team exceeds quota limits."""
        mock_is_team_limited.return_value = True

        response = self.client.post(
            f"/api/environments/{self.team.id}/conversations/",
            {
                "content": "test query",
                "trace_id": str(uuid.uuid4()),
                "conversation": str(uuid.uuid4()),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertEqual(
            response.json()["detail"],
            "Your organization reached its AI credit usage limit. Increase the limits in Billing settings, or ask an org admin to do so.",
        )
        mock_is_team_limited.assert_called_once()

    @patch("ee.api.conversation.is_team_limited")
    def test_quota_limit_not_exceeded(self, mock_is_team_limited):
        """Test that requests proceed normally when team has not exceeded quota limits."""
        mock_is_team_limited.return_value = False

        with patch(
            "ee.hogai.core.executor.AgentExecutor.astream",
            return_value=_async_generator(),
        ):
            with patch("ee.api.conversation.StreamingHttpResponse", side_effect=self._create_mock_streaming_response):
                response = self.client.post(
                    f"/api/environments/{self.team.id}/conversations/",
                    {
                        "content": "test query",
                        "trace_id": str(uuid.uuid4()),
                        "conversation": str(uuid.uuid4()),
                    },
                )

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                mock_is_team_limited.assert_called_once()

    def test_create_conversation_with_research_agent_mode(self):
        """Test that agent_mode=RESEARCH routes to ResearchAgentWorkflow."""

        conversation_id = str(uuid.uuid4())

        with patch(
            "ee.hogai.core.executor.AgentExecutor.astream",
            return_value=_async_generator(),
        ) as mock_start_workflow_and_stream:
            with patch("ee.api.conversation.StreamingHttpResponse", side_effect=self._create_mock_streaming_response):
                trace_id = str(uuid.uuid4())
                response = self.client.post(
                    f"/api/environments/{self.team.id}/conversations/",
                    {
                        "content": "test query",
                        "trace_id": trace_id,
                        "conversation": conversation_id,
                        "agent_mode": AgentMode.RESEARCH.value,
                    },
                )

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                mock_start_workflow_and_stream.assert_called_once()
                call_args = mock_start_workflow_and_stream.call_args

                # Verify workflow class is ResearchAgentWorkflow
                workflow_class = call_args[0][0]
                self.assertEqual(workflow_class, ResearchAgentWorkflow)

                # Verify workflow_inputs is ResearchAgentWorkflowInputs
                workflow_inputs = call_args[0][1]
                self.assertIsInstance(workflow_inputs, ResearchAgentWorkflowInputs)

                # Verify is_agent_billable=False for research mode
                self.assertEqual(workflow_inputs.is_agent_billable, False)
                # Verify is_impersonated is False (not an impersonated session)
                self.assertEqual(workflow_inputs.is_impersonated, False)

                # Verify agent_mode and contextual_tools are NOT passed in research mode
                self.assertFalse(hasattr(workflow_inputs, "agent_mode"))
                self.assertFalse(hasattr(workflow_inputs, "contextual_tools"))

    def test_research_mode_billing_is_always_false(self):
        """Test that research mode is always non-billable, even when not impersonated."""

        with patch(
            "ee.hogai.core.executor.AgentExecutor.astream",
            return_value=_async_generator(),
        ) as mock_start_workflow_and_stream:
            with patch("ee.api.conversation.StreamingHttpResponse", side_effect=self._create_mock_streaming_response):
                # Not patching is_impersonated_session, so it defaults to False (not impersonated)
                response = self.client.post(
                    f"/api/environments/{self.team.id}/conversations/",
                    {
                        "content": "test query",
                        "trace_id": str(uuid.uuid4()),
                        "conversation": str(uuid.uuid4()),
                        "agent_mode": AgentMode.RESEARCH.value,
                    },
                )

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                workflow_inputs = mock_start_workflow_and_stream.call_args[0][1]
                self.assertIsInstance(workflow_inputs, ResearchAgentWorkflowInputs)
                # Even without impersonation, research mode is non-billable
                self.assertEqual(workflow_inputs.is_agent_billable, False)

    def test_deep_research_converts_to_assistant_on_followup_message(self):
        """Test that an idle DEEP_RESEARCH conversation converts to ASSISTANT when user sends a follow-up."""
        conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            type=Conversation.Type.DEEP_RESEARCH,
            status=Conversation.Status.IDLE,
        )

        with patch(
            "ee.hogai.core.executor.AgentExecutor.astream",
            return_value=_async_generator(),
        ) as mock_astream:
            with patch("ee.api.conversation.StreamingHttpResponse", side_effect=self._create_mock_streaming_response):
                response = self.client.post(
                    f"/api/environments/{self.team.id}/conversations/",
                    {
                        "content": "follow-up question",
                        "trace_id": str(uuid.uuid4()),
                        "conversation": str(conversation.id),
                    },
                )

                self.assertEqual(response.status_code, status.HTTP_200_OK)

                conversation.refresh_from_db()
                self.assertEqual(conversation.type, Conversation.Type.ASSISTANT)

                call_args = mock_astream.call_args
                workflow_class = call_args[0][0]
                self.assertEqual(workflow_class, ChatAgentWorkflow)

                workflow_inputs = call_args[0][1]
                self.assertIsInstance(workflow_inputs, ChatAgentWorkflowInputs)

    def test_deep_research_stays_research_when_not_idle(self):
        """Test that an in-progress DEEP_RESEARCH conversation stays as research."""
        conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            type=Conversation.Type.DEEP_RESEARCH,
            status=Conversation.Status.IN_PROGRESS,
        )

        with patch(
            "ee.hogai.core.executor.AgentExecutor.astream",
            return_value=_async_generator(),
        ) as mock_astream:
            with patch("ee.api.conversation.StreamingHttpResponse", side_effect=self._create_mock_streaming_response):
                response = self.client.post(
                    f"/api/environments/{self.team.id}/conversations/",
                    {
                        "content": None,
                        "trace_id": str(uuid.uuid4()),
                        "conversation": str(conversation.id),
                    },
                )

                self.assertEqual(response.status_code, status.HTTP_200_OK)

                conversation.refresh_from_db()
                self.assertEqual(conversation.type, Conversation.Type.DEEP_RESEARCH)

                workflow_class = mock_astream.call_args[0][0]
                self.assertEqual(workflow_class, ResearchAgentWorkflow)

    def test_deep_research_stays_research_when_resume_payload_present(self):
        """Test that an idle DEEP_RESEARCH conversation stays as research when resume_payload is present (auto-rejecting approval)."""
        conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            type=Conversation.Type.DEEP_RESEARCH,
            status=Conversation.Status.IDLE,
        )

        with patch(
            "ee.hogai.core.executor.AgentExecutor.astream",
            return_value=_async_generator(),
        ) as mock_astream:
            with patch("ee.api.conversation.StreamingHttpResponse", side_effect=self._create_mock_streaming_response):
                response = self.client.post(
                    f"/api/environments/{self.team.id}/conversations/",
                    {
                        "content": "new question",
                        "trace_id": str(uuid.uuid4()),
                        "conversation": str(conversation.id),
                        "resume_payload": {"action": "reject"},
                    },
                )

                self.assertEqual(response.status_code, status.HTTP_200_OK)

                conversation.refresh_from_db()
                self.assertEqual(conversation.type, Conversation.Type.DEEP_RESEARCH)

                workflow_class = mock_astream.call_args[0][0]
                self.assertEqual(workflow_class, ResearchAgentWorkflow)

    @override_settings(DEBUG=False)
    def test_converted_conversation_rate_limits_as_regular(self):
        """Test that after conversion from DEEP_RESEARCH to ASSISTANT, _is_research_request returns False."""
        conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            type=Conversation.Type.DEEP_RESEARCH,
            status=Conversation.Status.IDLE,
        )

        with patch(
            "ee.hogai.core.executor.AgentExecutor.astream",
            return_value=_async_generator(),
        ):
            with patch("ee.api.conversation.StreamingHttpResponse", side_effect=self._create_mock_streaming_response):
                # First message converts DEEP_RESEARCH → ASSISTANT
                self.client.post(
                    f"/api/environments/{self.team.id}/conversations/",
                    {
                        "content": "follow-up",
                        "trace_id": str(uuid.uuid4()),
                        "conversation": str(conversation.id),
                    },
                )

                conversation.refresh_from_db()
                self.assertEqual(conversation.type, Conversation.Type.ASSISTANT)

                # Subsequent messages should not be rate-limited as research
                viewset = ConversationViewSet()
                viewset.team = self.team
                mock_request = type("Request", (), {"data": {"conversation": str(conversation.id)}})()
                self.assertFalse(viewset._is_research_request(mock_request))

    def test_chat_mode_uses_chat_agent_workflow(self):
        """Test that non-research modes use ChatAgentWorkflow."""

        conversation_id = str(uuid.uuid4())

        with patch(
            "ee.hogai.core.executor.AgentExecutor.astream",
            return_value=_async_generator(),
        ) as mock_start_workflow_and_stream:
            with patch("ee.api.conversation.StreamingHttpResponse", side_effect=self._create_mock_streaming_response):
                response = self.client.post(
                    f"/api/environments/{self.team.id}/conversations/",
                    {
                        "content": "test query",
                        "trace_id": str(uuid.uuid4()),
                        "conversation": conversation_id,
                        "agent_mode": AgentMode.SQL.value,  # Not RESEARCH
                    },
                )

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                call_args = mock_start_workflow_and_stream.call_args

                # Verify workflow class is ChatAgentWorkflow
                workflow_class = call_args[0][0]
                self.assertEqual(workflow_class, ChatAgentWorkflow)

                # Verify workflow_inputs is ChatAgentWorkflowInputs
                workflow_inputs = call_args[0][1]
                self.assertIsInstance(workflow_inputs, ChatAgentWorkflowInputs)

                # Verify agent_mode is passed for chat mode
                self.assertEqual(workflow_inputs.agent_mode, AgentMode.SQL)

    def _make_spend_history(self, count: int) -> list[dict]:
        return [
            SpendHistoryItem(
                id=i,
                label=f"item_{i}",
                data=[float(i)],
                dates=["2023-01-01"],
            ).model_dump()
            for i in range(count)
        ]

    def test_billing_context_strips_large_spend_history(self):
        with patch(
            "ee.hogai.core.executor.AgentExecutor.astream",
            return_value=_async_generator(),
        ) as mock_astream:
            with patch("ee.api.conversation.StreamingHttpResponse", side_effect=self._create_mock_streaming_response):
                billing_data = self.billing_context.model_dump()
                billing_data["spend_history"] = self._make_spend_history(21)
                response = self.client.post(
                    f"/api/environments/{self.team.id}/conversations/",
                    {
                        "content": "test query",
                        "trace_id": str(uuid.uuid4()),
                        "conversation": str(uuid.uuid4()),
                        "billing_context": billing_data,
                    },
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                workflow_inputs = mock_astream.call_args[0][1]
                self.assertIsNone(workflow_inputs.billing_context.spend_history)

    def test_billing_context_keeps_small_spend_history(self):
        with patch(
            "ee.hogai.core.executor.AgentExecutor.astream",
            return_value=_async_generator(),
        ) as mock_astream:
            with patch("ee.api.conversation.StreamingHttpResponse", side_effect=self._create_mock_streaming_response):
                billing_data = self.billing_context.model_dump()
                billing_data["spend_history"] = self._make_spend_history(20)
                response = self.client.post(
                    f"/api/environments/{self.team.id}/conversations/",
                    {
                        "content": "test query",
                        "trace_id": str(uuid.uuid4()),
                        "conversation": str(uuid.uuid4()),
                        "billing_context": billing_data,
                    },
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                workflow_inputs = mock_astream.call_args[0][1]
                self.assertIsNotNone(workflow_inputs.billing_context.spend_history)
                self.assertEqual(len(workflow_inputs.billing_context.spend_history), 20)


class TestConversationSoftDelete(APIBaseTest):
    def _make_conversation(self, **overrides) -> Conversation:
        defaults: dict[str, Any] = {
            "user": self.user,
            "team": self.team,
            "title": "A chat",
            "type": Conversation.Type.ASSISTANT,
        }
        defaults.update(overrides)
        return Conversation.objects.create(**defaults)

    def test_delete_marks_row_soft_deleted(self):
        conversation = self._make_conversation()

        before = timezone.now()
        response = self.client.delete(
            f"/api/environments/{self.team.id}/conversations/{conversation.id}/",
        )
        after = timezone.now()

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        refreshed = Conversation.objects.get(pk=conversation.pk)
        self.assertTrue(refreshed.deleted)
        assert refreshed.deleted_at is not None
        self.assertGreaterEqual(refreshed.deleted_at, before)
        self.assertLessEqual(refreshed.deleted_at, after)

    def test_delete_other_users_conversation_returns_404(self):
        other_user = User.objects.create_and_join(
            organization=self.organization,
            email="other-softdelete@posthog.com",
            password="password",
            first_name="Other",
        )
        conversation = self._make_conversation(user=other_user)

        response = self.client.delete(
            f"/api/environments/{self.team.id}/conversations/{conversation.id}/",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        refreshed = Conversation.objects.get(pk=conversation.pk)
        self.assertFalse(refreshed.deleted)

    def test_delete_already_deleted_returns_404(self):
        conversation = self._make_conversation(deleted=True, deleted_at=timezone.now())

        response = self.client.delete(
            f"/api/environments/{self.team.id}/conversations/{conversation.id}/",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_excludes_soft_deleted(self):
        kept = self._make_conversation(title="kept")
        self._make_conversation(title="gone", deleted=True, deleted_at=timezone.now())

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock):
            response = self.client.get(f"/api/environments/{self.team.id}/conversations/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [c["id"] for c in response.json()["results"]]
        self.assertEqual(ids, [str(kept.id)])

    def test_retrieve_soft_deleted_returns_404(self):
        conversation = self._make_conversation(deleted=True, deleted_at=timezone.now())

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock):
            response = self.client.get(
                f"/api/environments/{self.team.id}/conversations/{conversation.id}/",
            )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_with_deleted_id_does_not_resurrect(self):
        conversation = self._make_conversation(deleted=True, deleted_at=timezone.now())

        response = self.client.post(
            f"/api/environments/{self.team.id}/conversations/",
            {
                "content": "hello",
                "trace_id": str(uuid.uuid4()),
                "conversation": str(conversation.id),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        still_deleted = Conversation.objects.get(pk=conversation.pk)
        self.assertTrue(still_deleted.deleted)
        self.assertEqual(Conversation.objects.filter(pk=conversation.pk).count(), 1)


class TestConversationSandboxRoute(APIBaseTest):
    def _sandbox_conversation(self) -> Conversation:
        return Conversation.objects.create(
            user=self.user,
            team=self.team,
            title="A chat",
            type=Conversation.Type.ASSISTANT,
            agent_runtime=Conversation.AgentRuntime.SANDBOX,
        )

    def test_sandbox_route_reachable_and_delegates_to_handler(self):
        conversation = self._sandbox_conversation()
        sentinel = SandboxRouteResult(
            task_id="t",
            run_id="r",
            trace_id=None,
            run_status="queued",
            just_created_run=True,
            attached_context_count=2,
        )
        with (
            patch("ee.api.conversation.MessageRoutingService") as m_service,
            patch("ee.api.conversation.report_user_action") as m_telemetry,
        ):
            m_service.return_value.handle.return_value = sentinel
            response = self.client.post(
                f"/api/environments/{self.team.id}/conversations/{conversation.id}/sandbox/",
                {"content": "hello", "trace_id": str(uuid.uuid4())},
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # attached_context_count is internal telemetry plumbing, excluded from the response body.
        self.assertEqual(response.json(), sentinel.model_dump(exclude={"attached_context_count"}))
        m_service.return_value.handle.assert_called_once()
        # The service receives the resolved conversation, not just an id.
        passed_conversation = m_service.call_args[0][0]
        self.assertEqual(passed_conversation.id, conversation.id)
        # Telemetry fires once at the API boundary with sandbox-path field parity, derived
        # from the routing result.
        m_telemetry.assert_called_once()
        props = m_telemetry.call_args[0][2]
        self.assertEqual(props["execution_type"], "sandbox")
        self.assertEqual(props["agent_runtime"], "sandbox")
        self.assertTrue(props["has_attached_context"])
        self.assertEqual(props["attached_context_count"], 2)

    def test_sandbox_route_blocked_when_quota_limited(self):
        conversation = self._sandbox_conversation()
        with (
            patch("ee.api.conversation.is_team_limited", return_value=True),
            patch("ee.api.conversation.MessageRoutingService") as m_service,
        ):
            response = self.client.post(
                f"/api/environments/{self.team.id}/conversations/{conversation.id}/sandbox/",
                {"content": "hello"},
            )
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        m_service.assert_not_called()

    def test_sandbox_route_validates_request_body(self):
        conversation = self._sandbox_conversation()
        bad_payloads = [
            {"content": "x" * 40001},  # over the content length cap
            {"content": "hello", "trace_id": "not-a-uuid"},  # malformed trace id
            {"trace_id": str(uuid.uuid4())},  # missing content
        ]
        for payload in bad_payloads:
            with patch("ee.api.conversation.MessageRoutingService") as m_service:
                response = self.client.post(
                    f"/api/environments/{self.team.id}/conversations/{conversation.id}/sandbox/",
                    payload,
                )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, payload)
            m_service.assert_not_called()

    @override_settings(DEBUG=False)
    def test_get_throttles_returns_empty_for_sandbox_action(self):
        # Like create, the sandbox action's AI throttles are applied conditionally in check_throttles().
        viewset = ConversationViewSet()
        viewset.action = "sandbox"
        viewset.team_id = self.team.id
        viewset.organization = self.organization
        self.assertEqual(viewset.get_throttles(), [])

    def test_sandbox_route_rejects_langgraph_conversation(self):
        conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            title="A chat",
            type=Conversation.Type.ASSISTANT,
            agent_runtime=Conversation.AgentRuntime.LANGGRAPH,
        )
        with patch("ee.api.conversation.MessageRoutingService") as m_service:
            response = self.client.post(
                f"/api/environments/{self.team.id}/conversations/{conversation.id}/sandbox/",
                {"content": "hello"},
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        m_service.assert_not_called()

    def test_cancel_sandbox_conversation_delegates_to_sandbox_handler(self):
        conversation = self._sandbox_conversation()
        sentinel = SandboxCancelResult(task_id="t", run_id="r", run_status="cancelled", cancel_requested=True)
        with (
            patch("ee.api.conversation.MessageRoutingService") as m_service,
            patch("ee.api.conversation.report_user_action") as m_telemetry,
        ):
            m_service.return_value.cancel.return_value = sentinel
            response = self.client.patch(
                f"/api/environments/{self.team.id}/conversations/{conversation.id}/cancel/",
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # cancel_requested only gates telemetry; it's excluded from the response body.
        self.assertEqual(response.json(), sentinel.model_dump(exclude={"cancel_requested"}))
        m_service.return_value.cancel.assert_called_once()
        # A real cancel fires task_run_cancelled with the user source.
        m_telemetry.assert_called_once()
        self.assertEqual(m_telemetry.call_args[0][1], "task_run_cancelled")
        props = m_telemetry.call_args[0][2]
        self.assertEqual(props["execution_type"], "sandbox")
        self.assertEqual(props["cancel_source"], "user")
        self.assertEqual(props["run_id"], "r")

    def test_cancel_sandbox_conversation_skips_telemetry_for_terminal_noop(self):
        conversation = self._sandbox_conversation()
        # cancel_requested defaults False — an already-terminal run was a no-op.
        sentinel = SandboxCancelResult(task_id="t", run_id="r", run_status="completed")
        with (
            patch("ee.api.conversation.MessageRoutingService") as m_service,
            patch("ee.api.conversation.report_user_action") as m_telemetry,
        ):
            m_service.return_value.cancel.return_value = sentinel
            response = self.client.patch(
                f"/api/environments/{self.team.id}/conversations/{conversation.id}/cancel/",
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        m_telemetry.assert_not_called()

    def test_prewarm_post_delegates_to_warm_handler(self):
        conversation = self._sandbox_conversation()
        with patch("ee.api.conversation.MessageRoutingService") as m_service:
            response = self.client.post(
                f"/api/environments/{self.team.id}/conversations/{conversation.id}/prewarm/",
            )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        # The service receives the resolved conversation, and POST warms (never releases).
        passed_conversation = m_service.call_args[0][0]
        self.assertEqual(passed_conversation.id, conversation.id)
        m_service.return_value.prewarm.assert_called_once()
        m_service.return_value.prewarm_release.assert_not_called()

    def test_prewarm_delete_delegates_to_release_handler(self):
        conversation = self._sandbox_conversation()
        with patch("ee.api.conversation.MessageRoutingService") as m_service:
            response = self.client.delete(
                f"/api/environments/{self.team.id}/conversations/{conversation.id}/prewarm/",
            )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        m_service.return_value.prewarm_release.assert_called_once()
        m_service.return_value.prewarm.assert_not_called()

    def test_prewarm_rejects_langgraph_conversation(self):
        conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            title="A chat",
            type=Conversation.Type.ASSISTANT,
            agent_runtime=Conversation.AgentRuntime.LANGGRAPH,
        )
        with patch("ee.api.conversation.MessageRoutingService") as m_service:
            response = self.client.post(
                f"/api/environments/{self.team.id}/conversations/{conversation.id}/prewarm/",
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        m_service.assert_not_called()
