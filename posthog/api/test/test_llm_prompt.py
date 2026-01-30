from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models.llm_prompt import LLMPrompt


@patch("posthog.permissions.posthoganalytics.feature_enabled", return_value=True)
class TestLLMPromptAPI(APIBaseTest):
    def test_create_prompt_with_unique_name_succeeds(self, mock_feature_enabled):
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_prompts/",
            data={
                "name": "my-prompt",
                "prompt": "You are a helpful assistant.",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert LLMPrompt.objects.filter(team=self.team, name="my-prompt").exists()

    def test_create_prompt_with_duplicate_name_fails(self, mock_feature_enabled):
        LLMPrompt.objects.create(
            team=self.team,
            name="my-prompt",
            prompt="Original prompt",
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_prompts/",
            data={
                "name": "my-prompt",
                "prompt": "Duplicate prompt",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "name"
        assert response.json()["detail"] == "A prompt with this name already exists."

    def test_update_prompt_to_duplicate_name_fails(self, mock_feature_enabled):
        LLMPrompt.objects.create(
            team=self.team,
            name="existing-prompt",
            prompt="Content 1",
            created_by=self.user,
        )
        prompt_to_update = LLMPrompt.objects.create(
            team=self.team,
            name="another-prompt",
            prompt="Content 2",
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_prompts/{prompt_to_update.id}/",
            data={"name": "existing-prompt"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "name"
        assert response.json()["detail"] == "A prompt with this name already exists."

    def test_create_prompt_with_same_name_as_deleted_prompt_succeeds(self, mock_feature_enabled):
        LLMPrompt.objects.create(
            team=self.team,
            name="deleted-prompt",
            prompt="Original content",
            created_by=self.user,
            deleted=True,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_prompts/",
            data={
                "name": "deleted-prompt",
                "prompt": "New content",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert LLMPrompt.objects.filter(team=self.team, name="deleted-prompt", deleted=False).exists()

    def test_prompt_name_unique_per_team(self, mock_feature_enabled):
        from posthog.models import Team

        other_team = Team.objects.create(organization=self.organization, name="Other team")

        LLMPrompt.objects.create(
            team=self.team,
            name="shared-name",
            prompt="Content for team 1",
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/environments/{other_team.id}/llm_prompts/",
            data={
                "name": "shared-name",
                "prompt": "Content for team 2",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_update_prompt_content_without_name_change_succeeds(self, mock_feature_enabled):
        prompt = LLMPrompt.objects.create(
            team=self.team,
            name="my-prompt",
            prompt="Original content",
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_prompts/{prompt.id}/",
            data={"prompt": "Updated content"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        prompt.refresh_from_db()
        assert prompt.prompt == "Updated content"

    def test_soft_delete_prompt(self, mock_feature_enabled):
        prompt = LLMPrompt.objects.create(
            team=self.team,
            name="to-be-deleted",
            prompt="Content",
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_prompts/{prompt.id}/",
            data={"deleted": True},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        prompt.refresh_from_db()
        assert prompt.deleted is True

    def test_hard_delete_forbidden(self, mock_feature_enabled):
        prompt = LLMPrompt.objects.create(
            team=self.team,
            name="cannot-hard-delete",
            prompt="Content",
            created_by=self.user,
        )

        response = self.client.delete(f"/api/environments/{self.team.id}/llm_prompts/{prompt.id}/")

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_list_excludes_deleted_prompts(self, mock_feature_enabled):
        LLMPrompt.objects.create(
            team=self.team,
            name="active-prompt",
            prompt="Content",
            created_by=self.user,
            deleted=False,
        )
        LLMPrompt.objects.create(
            team=self.team,
            name="deleted-prompt",
            prompt="Content",
            created_by=self.user,
            deleted=True,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/")

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["name"] == "active-prompt"

    def test_fetch_prompt_by_name_succeeds(self, mock_feature_enabled):
        prompt = LLMPrompt.objects.create(
            team=self.team,
            name="test-prompt",
            prompt="You are a helpful assistant.",
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/name/test-prompt/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == str(prompt.id)
        assert response.json()["name"] == "test-prompt"
        assert response.json()["prompt"] == "You are a helpful assistant."

    def test_fetch_prompt_by_name_not_found(self, mock_feature_enabled):
        response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/name/non-existent/")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "not found" in response.json()["detail"].lower()

    def test_fetch_deleted_prompt_by_name_returns_not_found(self, mock_feature_enabled):
        LLMPrompt.objects.create(
            team=self.team,
            name="deleted-prompt",
            prompt="Content",
            created_by=self.user,
            deleted=True,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/name/deleted-prompt/")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_fetch_prompt_by_name_other_team_not_accessible(self, mock_feature_enabled):
        from posthog.models import Team

        other_team = Team.objects.create(organization=self.organization, name="Other team")
        LLMPrompt.objects.create(
            team=other_team,
            name="other-team-prompt",
            prompt="Content",
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/name/other-team-prompt/")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_create_prompt_with_invalid_name_fails(self, mock_feature_enabled):
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_prompts/",
            data={
                "name": "invalid name with spaces",
                "prompt": "Content",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "name"
        assert "Only letters, numbers, hyphens (-) and underscores (_) are allowed" in response.json()["detail"]

    def test_create_prompt_with_valid_name_characters(self, mock_feature_enabled):
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_prompts/",
            data={
                "name": "valid-name_123",
                "prompt": "Content",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["name"] == "valid-name_123"

    def test_returns_403_when_feature_flag_disabled(self, mock_class_feature_enabled):
        mock_class_feature_enabled.return_value = False

        LLMPrompt.objects.create(
            team=self.team,
            name="test-prompt",
            prompt="You are a helpful assistant.",
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/name/test-prompt/")

        assert response.status_code == status.HTTP_403_FORBIDDEN
