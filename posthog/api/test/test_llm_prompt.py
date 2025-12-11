from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models.llm_prompt import LLMPrompt


class TestLLMPromptAPI(APIBaseTest):
    def test_create_prompt_with_unique_name_succeeds(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_prompts/",
            data={
                "name": "My prompt",
                "prompt": "You are a helpful assistant.",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert LLMPrompt.objects.filter(team=self.team, name="My prompt").exists()

    def test_create_prompt_with_duplicate_name_fails(self):
        LLMPrompt.objects.create(
            team=self.team,
            name="My prompt",
            prompt="Original prompt",
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_prompts/",
            data={
                "name": "My prompt",
                "prompt": "Duplicate prompt",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "name"
        assert response.json()["detail"] == "A prompt with this name already exists."

    def test_update_prompt_to_duplicate_name_fails(self):
        LLMPrompt.objects.create(
            team=self.team,
            name="Existing prompt",
            prompt="Content 1",
            created_by=self.user,
        )
        prompt_to_update = LLMPrompt.objects.create(
            team=self.team,
            name="Another prompt",
            prompt="Content 2",
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_prompts/{prompt_to_update.id}/",
            data={"name": "Existing prompt"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "name"
        assert response.json()["detail"] == "A prompt with this name already exists."

    def test_create_prompt_with_same_name_as_deleted_prompt_succeeds(self):
        LLMPrompt.objects.create(
            team=self.team,
            name="Deleted prompt",
            prompt="Original content",
            created_by=self.user,
            deleted=True,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_prompts/",
            data={
                "name": "Deleted prompt",
                "prompt": "New content",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert LLMPrompt.objects.filter(team=self.team, name="Deleted prompt", deleted=False).exists()

    def test_prompt_name_unique_per_team(self):
        from posthog.models import Team

        other_team = Team.objects.create(organization=self.organization, name="Other team")

        LLMPrompt.objects.create(
            team=self.team,
            name="Shared name",
            prompt="Content for team 1",
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/environments/{other_team.id}/llm_prompts/",
            data={
                "name": "Shared name",
                "prompt": "Content for team 2",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_update_prompt_content_without_name_change_succeeds(self):
        prompt = LLMPrompt.objects.create(
            team=self.team,
            name="My prompt",
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

    def test_soft_delete_prompt(self):
        prompt = LLMPrompt.objects.create(
            team=self.team,
            name="To be deleted",
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

    def test_hard_delete_forbidden(self):
        prompt = LLMPrompt.objects.create(
            team=self.team,
            name="Cannot hard delete",
            prompt="Content",
            created_by=self.user,
        )

        response = self.client.delete(f"/api/environments/{self.team.id}/llm_prompts/{prompt.id}/")

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_list_excludes_deleted_prompts(self):
        LLMPrompt.objects.create(
            team=self.team,
            name="Active prompt",
            prompt="Content",
            created_by=self.user,
            deleted=False,
        )
        LLMPrompt.objects.create(
            team=self.team,
            name="Deleted prompt",
            prompt="Content",
            created_by=self.user,
            deleted=True,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/")

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["name"] == "Active prompt"
