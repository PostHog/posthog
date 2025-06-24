import datetime
import uuid
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone
from rest_framework import status

from ee.api.conversation import ConversationViewSet
from ee.hogai.assistant import Assistant
from ee.models.assistant import Conversation
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle
from posthog.test.base import APIBaseTest


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

    def _get_streaming_content(self, response):
        return b"".join(response.streaming_content)

    def test_create_conversation(self):
        with patch.object(Assistant, "_stream", return_value=["test response"]) as stream_mock:
            response = self.client.post(
                f"/api/environments/{self.team.id}/conversations/",
                {"content": "test query", "trace_id": str(uuid.uuid4())},
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(self._get_streaming_content(response), b"test response")
            self.assertEqual(Conversation.objects.count(), 1)
            conversation: Conversation = Conversation.objects.first()
            self.assertEqual(conversation.user, self.user)
            self.assertEqual(conversation.team, self.team)
            stream_mock.assert_called_once()

    def test_add_message_to_existing_conversation(self):
        with patch.object(Assistant, "_stream", return_value=["test response"]) as stream_mock:
            conversation = Conversation.objects.create(user=self.user, team=self.team)
            response = self.client.post(
                f"/api/environments/{self.team.id}/conversations/",
                {
                    "conversation": str(conversation.id),
                    "content": "test query",
                    "trace_id": str(uuid.uuid4()),
                },
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(self._get_streaming_content(response), b"test response")
            self.assertEqual(Conversation.objects.count(), 1)
            stream_mock.assert_called_once()

    def test_cant_access_other_users_conversation(self):
        conversation = Conversation.objects.create(user=self.other_user, team=self.team)

        self.client.force_login(self.user)
        response = self.client.post(
            f"/api/environments/{self.team.id}/conversations/",
            {"conversation": conversation.id, "content": "test query", "trace_id": str(uuid.uuid4())},
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cant_access_other_teams_conversation(self):
        conversation = Conversation.objects.create(user=self.user, team=self.other_team)
        response = self.client.post(
            f"/api/environments/{self.team.id}/conversations/",
            {"conversation": conversation.id, "content": "test query", "trace_id": str(uuid.uuid4())},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_invalid_message_format(self):
        response = self.client.post("/api/environments/@current/conversations/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rate_limit_burst(self):
        # Create multiple requests to trigger burst rate limit
        with patch.object(Assistant, "_stream", return_value=["test response"]):
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
        response = self.client.post(
            f"/api/environments/{self.team.id}/conversations/",
            {
                "conversation": "12345678-1234-5678-1234-567812345678",
                "content": "test query",
                "trace_id": str(uuid.uuid4()),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_deleted_conversation(self):
        # Create and then delete a conversation
        conversation = Conversation.objects.create(user=self.user, team=self.team)
        conversation_id = conversation.id
        conversation.delete()

        response = self.client.post(
            f"/api/environments/{self.team.id}/conversations/",
            {
                "conversation": str(conversation_id),
                "content": "test query",
                "trace_id": str(uuid.uuid4()),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated_request(self):
        self.client.logout()
        response = self.client.post(
            f"/api/environments/{self.team.id}/conversations/",
            {"content": "test query", "trace_id": str(uuid.uuid4())},
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_streaming_error_after_content_yields_proper_message(self):
        """Test that errors occurring after streaming content yield proper SSE-formatted error messages."""

        def stream_then_error():
            yield 'event: message\ndata: {"type": "human", "content": "Hello"}\n\n'
            yield 'event: message\ndata: {"type": "assistant", "content": "Hi there"}\n\n'
            raise RuntimeError("Backend processing error")

        with patch.object(Assistant, "_stream", side_effect=stream_then_error):
            response = self.client.post(
                f"/api/environments/{self.team.id}/conversations/",
                {"content": "test query", "trace_id": str(uuid.uuid4())},
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            # Get all streaming content
            content = self._get_streaming_content(response).decode("utf-8")

            # Should contain original messages
            self.assertIn('{"type": "human", "content": "Hello"}', content)
            self.assertIn('{"type": "assistant", "content": "Hi there"}', content)

            # Should contain error message at the end
            self.assertIn("event: message", content)
            self.assertIn('"type":"ai/failure"', content)
            self.assertIn("It looks like I'm having trouble answering this", content)

            # Verify the error message is the last thing the client sees
            # Split content into lines and find the last message event
            lines = content.strip().split("\n")
            last_message_event = None
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].startswith("event: message"):
                    # Find the corresponding data line
                    if i + 1 < len(lines) and lines[i + 1].startswith("data: "):
                        last_message_event = lines[i + 1]
                        break

            self.assertIsNotNone(last_message_event, "Should have a last message event")
            self.assertIn('"type":"ai/failure"', last_message_event)
            self.assertIn("It looks like I'm having trouble answering this", last_message_event)

    def test_cancel_conversation(self):
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Test conversation", type=Conversation.Type.ASSISTANT
        )
        response = self.client.patch(
            f"/api/environments/{self.team.id}/conversations/{conversation.id}/cancel/",
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        conversation.refresh_from_db()
        self.assertEqual(conversation.status, Conversation.Status.CANCELING)

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

    def test_cant_use_locked_conversation(self):
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, status=Conversation.Status.IN_PROGRESS
        )
        response = self.client.post(
            f"/api/environments/{self.team.id}/conversations/",
            {
                "conversation": str(conversation.id),
                "content": "test query",
                "trace_id": str(uuid.uuid4()),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

        conversation.status = Conversation.Status.CANCELING
        conversation.save()
        response = self.client.post(
            f"/api/environments/{self.team.id}/conversations/",
            {
                "conversation": str(conversation.id),
                "content": "test query",
                "trace_id": str(uuid.uuid4()),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_create_with_non_assistant_conversation(self):
        # Create a conversation with a non-assistant type
        conversation = Conversation.objects.create(user=self.user, team=self.team, type=Conversation.Type.TOOL_CALL)
        with patch.object(Assistant, "_stream", return_value=["test response"]):
            response = self.client.post(
                f"/api/environments/{self.team.id}/conversations/",
                {
                    "conversation": str(conversation.id),
                    "content": "test query",
                    "trace_id": str(uuid.uuid4()),
                },
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_with_no_title_conversation(self):
        # Create a conversation without a title
        conversation = Conversation.objects.create(user=self.user, team=self.team, title=None)
        with patch.object(Assistant, "_stream", return_value=["test response"]):
            response = self.client.post(
                f"/api/environments/{self.team.id}/conversations/",
                {
                    "conversation": str(conversation.id),
                    "content": "test query",
                    "trace_id": str(uuid.uuid4()),
                },
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_only_returns_assistant_conversations_with_title(self):
        # Create different types of conversations
        conversation1 = Conversation.objects.create(
            user=self.user, team=self.team, title="Conversation 1", type=Conversation.Type.ASSISTANT
        )
        Conversation.objects.create(user=self.user, team=self.team, title=None, type=Conversation.Type.ASSISTANT)
        Conversation.objects.create(user=self.user, team=self.team, title="Tool call", type=Conversation.Type.TOOL_CALL)

        with patch("ee.hogai.graph.graph.AssistantGraph.compile_full_graph"):
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

        with patch("ee.hogai.graph.graph.AssistantGraph.compile_full_graph"):
            response = self.client.get(f"/api/environments/{self.team.id}/conversations/{conversation.id}/")
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_retrieve_non_assistant_conversation_returns_404(self):
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Tool call", type=Conversation.Type.TOOL_CALL
        )

        with patch("ee.hogai.graph.graph.AssistantGraph.compile_full_graph"):
            response = self.client.get(f"/api/environments/{self.team.id}/conversations/{conversation.id}/")
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_conversation_serializer_returns_empty_messages_on_validation_error(self):
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Conversation with validation error", type=Conversation.Type.ASSISTANT
        )

        # Mock the get_state method to return data that will cause a validation error
        with patch("langgraph.graph.state.CompiledStateGraph.get_state") as mock_get_state:

            class MockSnapshot:
                values = {"invalid_key": "invalid_value"}  # Invalid structure for AssistantState

            mock_get_state.return_value = MockSnapshot()

            with patch("ee.hogai.graph.graph.AssistantGraph.compile_full_graph"):
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

        with patch("ee.hogai.graph.graph.AssistantGraph.compile_full_graph"):
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
