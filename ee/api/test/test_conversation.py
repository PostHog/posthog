from typing import cast
from unittest.mock import patch

from rest_framework import status

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

    def test_create_conversation(self):
        with patch("ee.hogai.assistant.Assistant.stream") as mock_assistant:
            mock_assistant.return_value = ["test response"]

            response = self.client.post(
                "/api/conversation/",
                {"message": {"query": "test query"}},
                content_type="application/json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.content, b"test response")
            self.assertEqual(Conversation.objects.count(), 1)
            conversation = Conversation.objects.first()
            self.assertEqual(conversation.user, self.user)
            self.assertEqual(conversation.team, self.team)

            mock_assistant.assert_called_once_with(
                self.team,
                conversation,
                {"query": "test query"},
                user=cast(User, self.user),
                send_conversation=True,
            )

    def test_add_message_to_existing_conversation(self):
        with patch("ee.hogai.assistant.Assistant.stream") as mock_assistant:
            mock_assistant.return_value = ["test response"]
            conversation = Conversation.objects.create(user=self.user, team=self.team)

            response = self.client.post(
                "/api/conversation/",
                {"id": conversation.id, "message": {"query": "test query"}},
                content_type="application/json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.content, b"test response")
            self.assertEqual(Conversation.objects.count(), 1)

            mock_assistant.assert_called_once_with(
                self.team,
                conversation,
                {"query": "test query"},
                user=cast(User, self.user),
                send_conversation=False,
            )

    def test_cant_access_other_users_conversation(self):
        conversation = Conversation.objects.create(user=self.other_user, team=self.team)

        self.client.force_login(self.user)
        response = self.client.post(
            "/api/conversation/",
            {"id": conversation.id, "message": {"query": "test query"}},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cant_access_other_teams_conversation(self):
        conversation = Conversation.objects.create(user=self.user, team=self.other_team)

        response = self.client.post(
            "/api/conversation/",
            {"id": conversation.id, "message": {"query": "test query"}},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_invalid_message_format(self):
        response = self.client.post(
            "/api/conversation/",
            {"message": "invalid format"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
