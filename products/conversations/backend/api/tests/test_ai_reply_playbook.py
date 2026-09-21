from posthog.test.base import APIBaseTest

from rest_framework import status

from products.conversations.backend.playbook import DEFAULT_SUPPORT_REPLY_INSTRUCTIONS, MAX_CUSTOM_INSTRUCTIONS_CHARS


class TestAIReplyPlaybookAPI(APIBaseTest):
    def test_get_inherited_playbook(self):
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/ai_reply_playbook/")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["is_customized"] is False
        assert body["custom_instructions"] is None
        assert DEFAULT_SUPPORT_REPLY_INSTRUCTIONS.strip() in body["inherited_instructions"]
        assert "Do not assume the product is PostHog." in body["inherited_instructions"]
        assert "diagnosing-missing-recordings" not in body["inherited_instructions"]
        assert body["max_chars"] == MAX_CUSTOM_INSTRUCTIONS_CHARS
        assert body["docs_source"] is None

    def test_get_customized_playbook(self):
        self.team.conversations_settings = {"ai_reply_custom_instructions": "Always greet first."}
        self.team.save(update_fields=["conversations_settings"])
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/ai_reply_playbook/")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["is_customized"] is True
        assert body["custom_instructions"] == "Always greet first."
        assert DEFAULT_SUPPORT_REPLY_INSTRUCTIONS.strip() in body["inherited_instructions"]

    def test_get_normalizes_saved_snapshot_to_inherit(self):
        inherited = DEFAULT_SUPPORT_REPLY_INSTRUCTIONS.strip()
        self.team.conversations_settings = {"ai_reply_custom_instructions": inherited}
        self.team.save(update_fields=["conversations_settings"])
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/ai_reply_playbook/")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["is_customized"] is False
        assert body["custom_instructions"] is None

    def test_get_posthog_overlay(self):
        self.team.conversations_settings = {"docs_source": "posthog"}
        self.team.save(update_fields=["conversations_settings"])
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/ai_reply_playbook/")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert "diagnosing-missing-recordings" in body["inherited_instructions"]
        assert body["docs_source"] == "posthog"
        assert body["posthog_overlay_version"] == 1
