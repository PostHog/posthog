import uuid

from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import Team
from posthog.models.user import User

from products.posthog_ai.backend.models.assistant import Conversation

from ee.hogai.queue import ConversationQueueStore, build_queue_message


class TestConversationQueue(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)
        self.queue_url = f"/api/environments/{self.team.id}/conversations/{self.conversation.id}/queue/"
        self.queue_limit = ConversationQueueStore(str(self.conversation.id)).max_messages

    def test_queue_list_returns_empty_for_new_conversation(self):
        response = self.client.get(self.queue_url)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"messages": [], "max_queue_messages": self.queue_limit}

    def test_queue_enqueue_adds_message_to_queue(self):
        response = self.client.post(self.queue_url, {"content": "hello"})

        assert response.status_code == status.HTTP_200_OK
        payload = response.json()
        assert payload["max_queue_messages"] == self.queue_limit
        assert len(payload["messages"]) == 1
        assert payload["messages"][0]["content"] == "hello"
        assert "id" in payload["messages"][0]

    def test_queue_enqueue_raises_conflict_when_full(self):
        self.client.post(self.queue_url, {"content": "one"})
        self.client.post(self.queue_url, {"content": "two"})

        response = self.client.post(self.queue_url, {"content": "three"})

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["error"] == "queue_full"

    def test_queue_update_modifies_content(self):
        response = self.client.post(self.queue_url, {"content": "hello"})
        queue_id = response.json()["messages"][0]["id"]

        response = self.client.patch(f"{self.queue_url}{queue_id}/", {"content": "updated"})

        assert response.status_code == status.HTTP_200_OK
        payload = response.json()
        assert payload["messages"][0]["content"] == "updated"

    def test_queue_update_nonexistent_returns_404(self):
        response = self.client.patch(f"{self.queue_url}missing/", {"content": "updated"})

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_queue_delete_removes_message(self):
        response = self.client.post(self.queue_url, {"content": "hello"})
        queue_id = response.json()["messages"][0]["id"]

        response = self.client.delete(f"{self.queue_url}{queue_id}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["messages"] == []

    def test_queue_clear_empties_queue(self):
        self.client.post(self.queue_url, {"content": "hello"})

        response = self.client.post(f"{self.queue_url}clear/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["messages"] == []

    def test_queue_access_denied_for_other_users_conversation(self):
        other_user = User.objects.create_and_join(
            organization=self.organization,
            email="other@posthog.com",
            password="password",
            first_name="Other",
        )
        other_conversation = Conversation.objects.create(team=self.team, user=other_user)

        response = self.client.get(f"/api/environments/{self.team.id}/conversations/{other_conversation.id}/queue/")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_queue_access_denied_for_other_teams_conversation(self):
        other_team = Team.objects.create(organization=self.organization, name="other")
        other_conversation = Conversation.objects.create(team=other_team, user=self.user)

        response = self.client.get(f"/api/environments/{self.team.id}/conversations/{other_conversation.id}/queue/")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_queue_access_missing_conversation_returns_404(self):
        missing_id = uuid.uuid4()

        response = self.client.get(f"/api/environments/{self.team.id}/conversations/{missing_id}/queue/")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_queue_store_consistency_after_clear(self):
        store = ConversationQueueStore(str(self.conversation.id))
        store.enqueue(build_queue_message(content="hello"))

        response = self.client.post(f"{self.queue_url}clear/")

        assert response.status_code == status.HTTP_200_OK
        assert store.list() == []
