from unittest.mock import patch

from rest_framework import status

from ee.hogai.assistant import Assistant
from ee.models.assistant import Conversation
from posthog.models.team.team import Team
from posthog.models.user import User
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
                "/api/projects/@current/conversations/",
                {"content": "test query"},
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
                "/api/projects/@current/conversations/",
                {
                    "conversation": str(conversation.id),
                    "content": "test query",
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
            "/api/projects/@current/conversations/",
            {"conversation": conversation.id, "content": "test query"},
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cant_access_other_teams_conversation(self):
        conversation = Conversation.objects.create(user=self.user, team=self.other_team)
        response = self.client.post(
            "/api/projects/@current/conversations/",
            {"conversation": conversation.id, "content": "test query"},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_invalid_message_format(self):
        response = self.client.post("/api/projects/@current/conversations/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
