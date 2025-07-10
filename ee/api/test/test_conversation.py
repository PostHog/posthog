import datetime
import uuid
from unittest.mock import AsyncMock, patch

from django.test import override_settings
from django.utils import timezone
from rest_framework import status

from ee.api.conversation import ConversationViewSet
from ee.hogai.assistant import Assistant
from ee.models.assistant import Conversation
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle
from posthog.schema import AssistantMessage
from posthog.test.base import APIBaseTest


async def _async_generator():
    yield ("message", AssistantMessage(content="test response"))


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

    def _get_streaming_content(self, response):
        return b"".join(response.streaming_content)

    def test_create_conversation(self):
        with patch("ee.api.conversation.Assistant.astream", return_value=_async_generator()) as stream_mock:
            response = self.client.post(
                f"/api/environments/{self.team.id}/conversations/",
                {"content": "test query", "trace_id": str(uuid.uuid4())},
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(self._get_streaming_content(response), _generator_serialized_value)
            self.assertEqual(Conversation.objects.count(), 1)
            conversation: Conversation = Conversation.objects.first()
            self.assertEqual(conversation.user, self.user)
            self.assertEqual(conversation.team, self.team)
            stream_mock.assert_called_once()

    def test_add_message_to_existing_conversation(self):
        with patch.object(
            Assistant,
            "astream",
            return_value=_async_generator(),
        ) as stream_mock:
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
            self.assertEqual(self._get_streaming_content(response), _generator_serialized_value)
            self.assertEqual(Conversation.objects.count(), 1)
            stream_mock.assert_called_once()

    def test_can_access_other_users_conversation_in_same_project(self):
        conversation = Conversation.objects.create(user=self.other_user, team=self.team)

        self.client.force_login(self.user)
        with patch("ee.api.conversation.Assistant.astream", return_value=_async_generator()):
            response = self.client.post(
                f"/api/environments/{self.team.id}/conversations/",
                {"conversation": conversation.id, "content": "test query", "trace_id": str(uuid.uuid4())},
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

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
        with patch.object(Assistant, "astream", return_value=_async_generator()):
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

    def test_none_content_in_post_request(self):
        """Test that when content is None in a POST request, the API handles it correctly and Assistant gets new_message=None."""
        with patch("ee.api.conversation.Assistant.astream", return_value=_async_generator()):
            with patch("ee.api.conversation.Assistant.__init__", return_value=None) as mock_init:
                response = self.client.post(
                    f"/api/environments/{self.team.id}/conversations/",
                    {"content": None, "trace_id": str(uuid.uuid4())},
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(self._get_streaming_content(response), _generator_serialized_value)
                mock_init.assert_called_once()
                # Check that new_message=None was passed
                self.assertIn("new_message", mock_init.call_args.kwargs)
                self.assertIsNone(mock_init.call_args.kwargs["new_message"])

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

    def test_can_cancel_other_users_conversation_in_same_project(self):
        conversation = Conversation.objects.create(user=self.other_user, team=self.team)
        response = self.client.patch(
            f"/api/environments/{self.team.id}/conversations/{conversation.id}/cancel/",
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        conversation.refresh_from_db()
        self.assertEqual(conversation.status, Conversation.Status.CANCELING)

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
        with patch.object(Assistant, "astream", return_value=_async_generator()):
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
        with patch.object(Assistant, "astream", return_value=_async_generator()):
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
            self.assertEqual(response.json()["id"], str(conversation.id))

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

    def test_cannot_access_other_users_conversation_for_create_action(self):
        """Test that create action cannot use other user's conversation ID"""
        conversation = Conversation.objects.create(
            user=self.other_user, team=self.team, title="Other user conversation", type=Conversation.Type.ASSISTANT
        )

        with patch("ee.api.conversation.Assistant.astream", return_value=_async_generator()):
            response = self.client.post(
                f"/api/environments/{self.team.id}/conversations/",
                {
                    "conversation": str(conversation.id),
                    "content": "test query",
                    "trace_id": str(uuid.uuid4()),
                },
            )
            # This should fail because create action filters by user=self.request.user
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_access_other_users_conversation_for_cancel_action(self):
        """Test that cancel action cannot use other user's conversation ID"""
        conversation = Conversation.objects.create(
            user=self.other_user, team=self.team, title="Other user conversation", type=Conversation.Type.ASSISTANT
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/conversations/{conversation.id}/cancel/",
        )
        # This should fail because cancel action filters by user=self.request.user
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

    def test_list_conversations_excludes_conversations_without_title(self):
        """Test that listing excludes conversations without title"""
        Conversation.objects.create(user=self.user, team=self.team, title=None, type=Conversation.Type.ASSISTANT)
        conversation_with_title = Conversation.objects.create(
            user=self.user, team=self.team, title="Valid conversation", type=Conversation.Type.ASSISTANT
        )

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock):
            response = self.client.get(f"/api/environments/{self.team.id}/conversations/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            results = response.json()["results"]
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["id"], str(conversation_with_title.id))

    def test_list_conversations_excludes_non_assistant_conversations(self):
        """Test that listing excludes non-assistant conversations"""
        Conversation.objects.create(user=self.user, team=self.team, title="Tool call", type=Conversation.Type.TOOL_CALL)
        assistant_conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Assistant conversation", type=Conversation.Type.ASSISTANT
        )

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock):
            response = self.client.get(f"/api/environments/{self.team.id}/conversations/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            results = response.json()["results"]
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["id"], str(assistant_conversation.id))

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
