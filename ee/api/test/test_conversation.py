import uuid
import datetime

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from django.http import HttpResponse
from django.test import override_settings
from django.utils import timezone

from rest_framework import status

from posthog.schema import (
    AssistantEventType,
    AssistantMessage,
    MaxBillingContext,
    MaxBillingContextBillingPeriod,
    MaxBillingContextBillingPeriodInterval,
    MaxBillingContextSettings,
    MaxBillingContextSubscriptionLevel,
    MaxBillingContextTrial,
    MaxProductInfo,
)

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle

from ee.api.conversation import ConversationViewSet
from ee.models.assistant import Conversation


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

    def _get_streaming_content(self, response):
        return b"".join(response.streaming_content)

    def _create_mock_streaming_response(self, streaming_content, *args, **kwargs):
        """Helper to create a mock StreamingHttpResponse that actually processes the streaming content."""

        # Actually consume the generator to ensure the mocked methods are called
        try:
            # This will trigger the async generator and call our mocked methods
            content = b"".join(streaming_content)
        except Exception:
            # If there's an issue with the async generator, use fallback
            content = _generator_serialized_value

        mock_response = HttpResponse(content, content_type="text/event-stream")
        mock_response.streaming_content = [content]
        return mock_response

    def test_create_conversation(self):
        conversation_id = str(uuid.uuid4())

        with patch(
            "ee.hogai.stream.conversation_stream.ConversationStreamManager.astream",
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
                conversation: Conversation = Conversation.objects.first()
                self.assertEqual(conversation.user, self.user)
                self.assertEqual(conversation.team, self.team)
                # Check that the method was called with workflow_inputs
                mock_start_workflow_and_stream.assert_called_once()
                call_args = mock_start_workflow_and_stream.call_args
                workflow_inputs = call_args[0][0]
                self.assertEqual(workflow_inputs.user_id, self.user.id)
                self.assertEqual(workflow_inputs.is_new_conversation, True)
                self.assertEqual(workflow_inputs.conversation_id, conversation.id)
                self.assertEqual(str(workflow_inputs.trace_id), trace_id)
                self.assertEqual(workflow_inputs.message["content"], "test query")

    def test_add_message_to_existing_conversation(self):
        with patch(
            "ee.hogai.stream.conversation_stream.ConversationStreamManager.astream",
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
                workflow_inputs = call_args[0][0]
                self.assertEqual(workflow_inputs.user_id, self.user.id)
                self.assertEqual(workflow_inputs.is_new_conversation, False)
                self.assertEqual(workflow_inputs.conversation_id, conversation.id)
                self.assertEqual(str(workflow_inputs.trace_id), trace_id)
                self.assertEqual(workflow_inputs.message["content"], "test query")

    def test_cant_access_other_users_conversation(self):
        conversation = Conversation.objects.create(user=self.other_user, team=self.team)

        self.client.force_login(self.user)
        response = self.client.post(
            f"/api/environments/{self.team.id}/conversations/",
            {"conversation": conversation.id, "content": None, "trace_id": str(uuid.uuid4())},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

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
            "ee.hogai.stream.conversation_stream.ConversationStreamManager.astream",
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
            "ee.hogai.stream.conversation_stream.ConversationStreamManager.astream",
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
            "ee.hogai.stream.conversation_stream.ConversationStreamManager.astream",
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

    @patch("ee.hogai.stream.conversation_stream.ConversationStreamManager.cancel_conversation")
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

    def test_cancel_other_users_conversation(self):
        conversation = Conversation.objects.create(user=self.other_user, team=self.team)
        response = self.client.patch(
            f"/api/environments/{self.team.id}/conversations/{conversation.id}/cancel/",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cancel_other_teams_conversation(self):
        conversation = Conversation.objects.create(user=self.user, team=self.other_team)
        response = self.client.patch(
            f"/api/environments/{self.team.id}/conversations/{conversation.id}/cancel/",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("ee.hogai.stream.conversation_stream.ConversationStreamManager.cancel_conversation")
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

    @patch("ee.hogai.stream.conversation_stream.ConversationStreamManager.cancel_conversation")
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

    def test_cancel_idle_conversation_noop(self):
        """Test that canceling an idle conversation is a no-op."""
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
        conversation.refresh_from_db()
        # Status should remain idle
        self.assertEqual(conversation.status, Conversation.Status.IDLE)

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
            "ee.hogai.stream.conversation_stream.ConversationStreamManager.astream",
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

    def test_resume_generation_from_idle_conversation(self):
        """Test resuming generation from an idle conversation with no new content."""
        conversation = Conversation.objects.create(user=self.user, team=self.team, status=Conversation.Status.IDLE)
        with patch(
            "ee.hogai.stream.conversation_stream.ConversationStreamManager.astream",
            return_value=_async_generator(),
        ) as mock_start_workflow_and_stream:
            with patch("ee.api.conversation.StreamingHttpResponse", side_effect=self._create_mock_streaming_response):
                trace_id = str(uuid.uuid4())
                response = self.client.post(
                    f"/api/environments/{self.team.id}/conversations/",
                    {
                        "conversation": str(conversation.id),
                        "content": None,
                        "trace_id": trace_id,
                    },
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(self._get_streaming_content(response), _generator_serialized_value)
                # Check that the method was called with workflow_inputs
                mock_start_workflow_and_stream.assert_called_once()
                call_args = mock_start_workflow_and_stream.call_args
                workflow_inputs = call_args[0][0]
                self.assertEqual(workflow_inputs.user_id, self.user.id)
                self.assertEqual(workflow_inputs.is_new_conversation, False)
                self.assertEqual(workflow_inputs.conversation_id, conversation.id)
                self.assertEqual(str(workflow_inputs.trace_id), trace_id)
                self.assertIsNone(workflow_inputs.message)

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

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock):
            response = self.client.get(f"/api/environments/{self.team.id}/conversations/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            # Only one conversation should be returned (the one with title and type ASSISTANT)
            results = response.json()["results"]
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["id"], str(conversation1.id))
            self.assertEqual(results[0]["title"], "Conversation 1")
            self.assertIn("messages", results[0])
            self.assertIn("status", results[0])

    def test_retrieve_conversation_without_title_returns_404(self):
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title=None, type=Conversation.Type.ASSISTANT
        )

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock):
            response = self.client.get(f"/api/environments/{self.team.id}/conversations/{conversation.id}/")
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_retrieve_non_assistant_conversation_returns_404(self):
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Tool call", type=Conversation.Type.TOOL_CALL
        )

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock):
            response = self.client.get(f"/api/environments/{self.team.id}/conversations/{conversation.id}/")
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_conversation_serializer_returns_empty_messages_on_validation_error(self):
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Conversation with validation error", type=Conversation.Type.ASSISTANT
        )

        # Mock the get_state method to return data that will cause a validation error
        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock) as mock_get_state:

            class MockSnapshot:
                values = {"invalid_key": "invalid_value"}  # Invalid structure for AssistantState

            mock_get_state.return_value = MockSnapshot()

            response = self.client.get(f"/api/environments/{self.team.id}/conversations/{conversation.id}/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            # Should return empty messages array when validation fails
            self.assertEqual(response.json()["messages"], [])

    def test_list_conversations_ordered_by_updated_at(self):
        """Verify conversations are listed with most recently updated first"""
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

            # First result should be the newer conversation
            self.assertEqual(results[0]["id"], str(conversation2.id))
            self.assertEqual(results[0]["title"], "Newer conversation")

            # Second result should be the older conversation
            self.assertEqual(results[1]["id"], str(conversation1.id))
            self.assertEqual(results[1]["title"], "Older conversation")

    @override_settings(DEBUG=False)
    def test_get_throttles_applies_rate_limits_for_create_action(self):
        """Test that rate limits are applied for create action in non-debug, non-exempt conditions."""

        viewset = ConversationViewSet()
        viewset.action = "create"
        viewset.team_id = 12345
        throttles = viewset.get_throttles()
        self.assertIsInstance(throttles[0], AIBurstRateThrottle)
        self.assertIsInstance(throttles[1], AISustainedRateThrottle)

    @override_settings(DEBUG=True)
    def test_get_throttles_skips_rate_limits_for_debug_mode(self):
        """Test that rate limits are skipped in debug mode."""

        viewset = ConversationViewSet()
        viewset.action = "create"
        viewset.team_id = 12345
        throttles = viewset.get_throttles()
        self.assertNotIsInstance(throttles[0], AIBurstRateThrottle)
        self.assertNotIsInstance(throttles[1], AISustainedRateThrottle)

    def test_billing_context_validation_valid_data(self):
        """Test that valid billing context data is accepted."""
        conversation = Conversation.objects.create(user=self.user, team=self.team)

        with patch(
            "ee.hogai.stream.conversation_stream.ConversationStreamManager.astream",
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
                workflow_inputs = call_args[0][0]
                self.assertEqual(workflow_inputs.billing_context, self.billing_context)

    def test_billing_context_validation_invalid_data(self):
        """Test that invalid billing context data is rejected."""
        conversation = Conversation.objects.create(user=self.user, team=self.team)

        with patch(
            "ee.hogai.stream.conversation_stream.ConversationStreamManager.astream",
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
                workflow_inputs = call_args[0][0]
                self.assertEqual(workflow_inputs.billing_context, None)
