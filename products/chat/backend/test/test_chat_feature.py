import pytest
from rest_framework import status

from posthog.models import Person, PersonalAPIKey
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal
from posthog.test.base import APIBaseTest, snapshot_postgres_queries
from products.chat.backend.models import ChatConversation


@pytest.mark.django_db
class TestChatEndpointCreateConversation(APIBaseTest):
    def setUp(self):
        super().setUp()
        # self.user, self.team are provided by APIBaseTest
        # self.client is also provided.

        self.personal_api_key_value = generate_random_token_personal()
        # Personal API keys are primarily user-scoped. Team access is via user or scoped_teams.
        PersonalAPIKey.objects.create(
            user=self.user,
            # team=self.team, # This field is deprecated on PersonalAPIKey model
            label="Test Chat Endpoint Key",
            secure_value=hash_key_value(self.personal_api_key_value),
            scopes=["*"],  # Broadest scope
            scoped_teams=[self.team.id],  # Explicitly scope to the test team
        )

        self.test_person = Person.objects.create(team=self.team, distinct_ids=["person_for_chat_creation"])
        self.chat_endpoint_url = "/api/chat/"

    @snapshot_postgres_queries
    def test_create_conversation_with_personal_api_key_in_body(self):
        """Test creating a conversation using a personal API key via token in JSON body."""
        payload = {
            "action": "create_conversation",
            "token": self.personal_api_key_value,  # Using "token" as the key in payload
            "distinct_id": "person_for_chat_creation",
            "title": "Conversation via Body Token",
            "source_url": "http://example.com/body_test",
            "message": "Hello from body token test!",
        }

        response = self.client.post(self.chat_endpoint_url, payload, content_type="application/json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        response_data = response.json()
        assert response_data.get("status") == "success"
        assert "conversation_id" in response_data

        conversation_id = response_data["conversation_id"]
        assert ChatConversation.objects.filter(id=conversation_id, team=self.team).exists()

        conversation = ChatConversation.objects.get(id=conversation_id)
        assert conversation.title == "Conversation via Body Token"
        assert str(conversation.person_uuid) == str(self.test_person.uuid)
        assert conversation.source_url == "http://example.com/body_test"

        assert conversation.messages.count() == 1
        assert conversation.messages.first().content == "Hello from body token test!"
