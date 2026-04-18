from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIRequestFactory

from posthog.api.llm_prompt import LLMPromptViewSet
from posthog.api.llm_prompt_serializers import MAX_PROMPT_PAYLOAD_BYTES
from posthog.api.services.llm_prompt import MAX_PROMPT_VERSION
from posthog.models.llm_prompt import LLMPrompt
from posthog.rate_limit import BurstRateThrottle, LLMPromptPublishBurstRateThrottle, SustainedRateThrottle


@patch("posthog.api.llm_prompt.posthoganalytics.feature_enabled", return_value=True)
class TestLLMPromptAPI(APIBaseTest):
    @parameterized.expand(
        [
            ("prompt_management_enabled", True, False, status.HTTP_200_OK),
            ("early_adopters_enabled", False, True, status.HTTP_200_OK),
            ("both_enabled", True, True, status.HTTP_200_OK),
            ("both_disabled", False, False, status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_prompt_api_permission_accepts_prompt_or_early_adopters_flag(
        self,
        mock_feature_enabled,
        _name,
        prompt_management_enabled,
        early_adopters_enabled,
        expected_status,
    ):
        def feature_flag_side_effect(flag, *_args, **_kwargs):
            return {
                "prompt-management": prompt_management_enabled,
                "llm-analytics-early-adopters": early_adopters_enabled,
            }.get(flag, False)

        mock_feature_enabled.side_effect = feature_flag_side_effect

        response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/")

        assert response.status_code == expected_status

    def create_prompt_version(
        self,
        *,
        name: str = "my-prompt",
        prompt: Any = "Prompt content",
        version: int = 1,
        is_latest: bool = True,
        deleted: bool = False,
    ) -> LLMPrompt:
        return LLMPrompt.objects.create(
            team=self.team,
            name=name,
            prompt=prompt,
            version=version,
            is_latest=is_latest,
            deleted=deleted,
            created_by=self.user,
        )

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
        assert response.json()["version"] == 1
        assert response.json()["is_latest"] is True
        assert response.json()["latest_version"] == 1
        assert response.json()["version_count"] == 1

    def test_create_prompt_with_duplicate_active_name_fails(self, mock_feature_enabled):
        self.create_prompt_version(name="my-prompt")

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_prompts/",
            data={"name": "my-prompt", "prompt": "Duplicate prompt"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "name"
        assert response.json()["detail"] == "A prompt with this name already exists."

    def test_create_prompt_with_same_name_as_archived_versions_restarts_at_version_one(self, mock_feature_enabled):
        self.create_prompt_version(name="archived-prompt", version=1, is_latest=False, deleted=True)
        self.create_prompt_version(name="archived-prompt", version=2, is_latest=False, deleted=True)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_prompts/",
            data={"name": "archived-prompt", "prompt": "New active prompt"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["version"] == 1
        assert response.json()["latest_version"] == 1

    def test_create_prompt_ignores_deleted_field(self, mock_feature_enabled):
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_prompts/",
            data={"name": "my-prompt", "prompt": "Prompt content", "deleted": True},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["deleted"] is False
        created_prompt = LLMPrompt.objects.get(team=self.team, name="my-prompt", version=1, deleted=False)
        assert created_prompt.deleted is False

    def test_create_prompt_rejects_payload_above_max_size(self, mock_feature_enabled):
        oversized_prompt = "x" * (MAX_PROMPT_PAYLOAD_BYTES + 1)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_prompts/",
            data={"name": "oversized-prompt", "prompt": oversized_prompt},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "prompt"
        assert "bytes or fewer" in response.json()["detail"]

    def test_retrieve_prompt_by_id_is_not_routed(self, mock_feature_enabled):
        prompt = self.create_prompt_version(name="original-name")

        response = self.client.get(
            f"/api/environments/{self.team.id}/llm_prompts/{prompt.id}/",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_prompt_by_id_is_not_routed(self, mock_feature_enabled):
        prompt = self.create_prompt_version(name="my-prompt", prompt="Original content")

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_prompts/{prompt.id}/",
            data={"prompt": "Updated content", "base_version": 1},
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_list_returns_only_latest_rows_for_active_version_histories(self, mock_feature_enabled):
        self.create_prompt_version(name="prompt-a", version=1, is_latest=False, prompt="v1")
        self.create_prompt_version(name="prompt-a", version=2, is_latest=True, prompt="v2")
        self.create_prompt_version(name="prompt-b", version=1, is_latest=True, prompt="only")

        response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/")

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert {prompt["name"] for prompt in results} == {"prompt-a", "prompt-b"}
        prompt_a = next(prompt for prompt in results if prompt["name"] == "prompt-a")
        assert prompt_a["version"] == 2
        assert prompt_a["latest_version"] == 2
        assert prompt_a["version_count"] == 2
        assert prompt_a["prompt"] == "v2"
        assert prompt_a["prompt_size_bytes"] > 0

    @parameterized.expand(
        [
            ("full", True, False),
            ("preview", False, True),
            ("none", False, False),
        ]
    )
    def test_list_content_mode(self, mock_feature_enabled, mode, has_prompt, has_preview):
        self.create_prompt_version(name="content-prompt", prompt="x" * 200)

        response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/?content={mode}")

        assert response.status_code == status.HTTP_200_OK
        prompt = response.json()["results"][0]
        assert ("prompt" in prompt) is has_prompt
        assert ("prompt_preview" in prompt) is has_preview
        assert prompt["prompt_size_bytes"] > 0
        if has_preview:
            assert len(prompt["prompt_preview"]) <= 163

    def test_list_includes_outline_parsed_from_prompt_markdown(self, mock_feature_enabled):
        self.create_prompt_version(name="outlined", prompt="# Role\nYou are helpful.\n## Tools\nsearch")

        response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/")

        assert response.status_code == status.HTTP_200_OK
        prompt = response.json()["results"][0]
        assert prompt["outline"] == [
            {"level": 1, "text": "Role"},
            {"level": 2, "text": "Tools"},
        ]

    def test_list_outline_is_present_even_when_content_none(self, mock_feature_enabled):
        self.create_prompt_version(name="outlined", prompt="# Role\n# Output")

        response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/?content=none")

        assert response.status_code == status.HTTP_200_OK
        prompt = response.json()["results"][0]
        assert "prompt" not in prompt
        assert "prompt_preview" not in prompt
        assert prompt["outline"] == [{"level": 1, "text": "Role"}, {"level": 1, "text": "Output"}]

    def test_list_outline_empty_for_non_markdown_prompt(self, mock_feature_enabled):
        self.create_prompt_version(name="plain", prompt="just text, no headings")

        response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"][0]["outline"] == []

    def test_list_can_order_by_prompt_size_bytes(self, mock_feature_enabled):
        self.create_prompt_version(name="small", prompt="abc")
        self.create_prompt_version(name="large", prompt="x" * 50)

        response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/?order_by=-prompt_size_bytes")

        assert response.status_code == status.HTTP_200_OK
        names = [prompt["name"] for prompt in response.json()["results"]]
        assert names == ["large", "small"]

    def test_fetch_prompt_by_name_returns_latest_by_default(self, mock_feature_enabled):
        first_version = self.create_prompt_version(name="test-prompt", version=1, is_latest=False, prompt="v1")
        latest_version = self.create_prompt_version(name="test-prompt", version=2, is_latest=True, prompt="v2")

        response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/name/test-prompt/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == str(latest_version.id)
        assert response.json()["prompt"] == "v2"
        assert response.json()["version"] == 2
        assert response.json()["latest_version"] == 2
        assert response.json()["version_count"] == 2
        assert response.json()["first_version_created_at"] == first_version.created_at.isoformat().replace(
            "+00:00", "Z"
        )
        assert "created_by" not in response.json()

    def test_fetch_prompt_by_name_includes_outline(self, mock_feature_enabled):
        self.create_prompt_version(name="outlined", prompt="# Role\n## Tools")

        response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/name/outlined/")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["prompt"] == "# Role\n## Tools"
        assert body["outline"] == [{"level": 1, "text": "Role"}, {"level": 2, "text": "Tools"}]

    @parameterized.expand(
        [
            ("full", True, False),
            ("preview", False, True),
            ("none", False, False),
        ]
    )
    def test_fetch_prompt_by_name_respects_content_mode(self, mock_feature_enabled, mode, has_prompt, has_preview):
        self.create_prompt_version(name="outlined", prompt="# Role\n" + ("x" * 300))

        response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/name/outlined/?content={mode}")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert ("prompt" in body) is has_prompt
        assert ("prompt_preview" in body) is has_preview
        assert body["outline"] == [{"level": 1, "text": "Role"}]
        if has_preview:
            assert len(body["prompt_preview"]) <= 163

    def test_fetch_prompt_by_name_with_explicit_version_returns_historical_version(self, mock_feature_enabled):
        first_version = self.create_prompt_version(name="test-prompt", version=1, is_latest=False, prompt="v1")
        self.create_prompt_version(name="test-prompt", version=2, is_latest=True, prompt="v2")

        response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/name/test-prompt/?version=1")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == str(first_version.id)
        assert response.json()["prompt"] == "v1"
        assert response.json()["version"] == 1
        assert response.json()["is_latest"] is False
        assert response.json()["latest_version"] == 2
        assert response.json()["version_count"] == 2

    def test_fetch_prompt_by_name_uses_latest_cache_after_first_load(self, mock_feature_enabled):
        self.create_prompt_version(name="cached-prompt", version=1, is_latest=True)
        from posthog.storage.llm_prompt_cache import llm_prompts_hypercache

        with patch.object(llm_prompts_hypercache, "load_fn", wraps=llm_prompts_hypercache.load_fn) as mock_load_fn:
            first_response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/name/cached-prompt/")
            second_response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/name/cached-prompt/")

        assert first_response.status_code == status.HTTP_200_OK
        assert second_response.status_code == status.HTTP_200_OK
        assert mock_load_fn.call_count == 1

    def test_fetch_prompt_by_name_uses_version_cache_for_historical_fetches(self, mock_feature_enabled):
        self.create_prompt_version(name="cached-prompt", version=1, is_latest=False, prompt="v1")
        self.create_prompt_version(name="cached-prompt", version=2, is_latest=True, prompt="v2")
        from posthog.storage.llm_prompt_cache import llm_prompts_hypercache

        latest_response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/name/cached-prompt/")
        assert latest_response.status_code == status.HTTP_200_OK

        with patch.object(llm_prompts_hypercache, "load_fn", wraps=llm_prompts_hypercache.load_fn) as mock_load_fn:
            first_response = self.client.get(
                f"/api/environments/{self.team.id}/llm_prompts/name/cached-prompt/?version=1"
            )
            second_response = self.client.get(
                f"/api/environments/{self.team.id}/llm_prompts/name/cached-prompt/?version=1"
            )

        assert first_response.status_code == status.HTTP_200_OK
        assert second_response.status_code == status.HTTP_200_OK
        assert mock_load_fn.call_count == 1

    def test_update_prompt_by_name_creates_new_immutable_row(self, mock_feature_enabled):
        original = self.create_prompt_version(name="publish-prompt", version=1, is_latest=True, prompt="v1")

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_prompts/name/publish-prompt/",
            data={"prompt": "v2", "base_version": 1},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        original.refresh_from_db()
        assert original.prompt == "v1"
        assert original.is_latest is False

        latest = LLMPrompt.objects.get(team=self.team, name="publish-prompt", version=2, deleted=False)
        assert latest.is_latest is True
        assert latest.prompt == "v2"
        assert response.json()["id"] == str(latest.id)
        assert response.json()["latest_version"] == 2
        assert response.json()["version_count"] == 2

    def test_update_prompt_by_name_falls_back_when_post_publish_refresh_misses_row(self, mock_feature_enabled):
        first_version = self.create_prompt_version(name="publish-prompt", version=1, is_latest=True, prompt="v1")

        with patch("posthog.api.services.llm_prompt.get_active_prompt_queryset", return_value=LLMPrompt.objects.none()):
            response = self.client.patch(
                f"/api/environments/{self.team.id}/llm_prompts/name/publish-prompt/",
                data={"prompt": "v2", "base_version": 1},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["version"] == 2
        assert response.json()["version_count"] == 2
        assert response.json()["first_version_created_at"] == first_version.created_at.isoformat().replace(
            "+00:00", "Z"
        )
        assert LLMPrompt.objects.filter(team=self.team, name="publish-prompt", version=2, deleted=False).exists()

    def test_update_prompt_by_name_returns_conflict_for_stale_base_version(self, mock_feature_enabled):
        self.create_prompt_version(name="publish-prompt", version=1, is_latest=False, prompt="v1")
        self.create_prompt_version(name="publish-prompt", version=2, is_latest=True, prompt="v2")

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_prompts/name/publish-prompt/",
            data={"prompt": "stale", "base_version": 1},
            format="json",
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["current_version"] == 2

    def test_update_prompt_by_name_rejects_payload_above_max_size(self, mock_feature_enabled):
        self.create_prompt_version(name="publish-prompt", version=1, is_latest=True, prompt="v1")
        oversized_prompt = "x" * (MAX_PROMPT_PAYLOAD_BYTES + 1)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_prompts/name/publish-prompt/",
            data={"prompt": oversized_prompt, "base_version": 1},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "prompt"
        assert "bytes or fewer" in response.json()["detail"]

    def test_update_prompt_by_name_rejects_publish_when_version_limit_reached(self, mock_feature_enabled):
        self.create_prompt_version(name="publish-prompt", version=MAX_PROMPT_VERSION, is_latest=True, prompt="v-limit")

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_prompts/name/publish-prompt/",
            data={"prompt": "v-over-limit", "base_version": MAX_PROMPT_VERSION},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert str(MAX_PROMPT_VERSION) in response.json()["detail"]
        assert LLMPrompt.objects.filter(team=self.team, name="publish-prompt", deleted=False).count() == 1

    def test_update_prompt_by_name_with_edits_applies_find_replace(self, mock_feature_enabled):
        self.create_prompt_version(name="edit-prompt", version=1, is_latest=True, prompt="You are a helpful assistant.")

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_prompts/name/edit-prompt/",
            data={
                "edits": [{"old": "helpful assistant", "new": "expert coding assistant"}],
                "base_version": 1,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["version"] == 2
        latest = LLMPrompt.objects.get(team=self.team, name="edit-prompt", version=2, deleted=False)
        assert latest.prompt == "You are a expert coding assistant."

    def test_update_prompt_by_name_with_multiple_edits_applies_sequentially(self, mock_feature_enabled):
        self.create_prompt_version(name="multi-edit", version=1, is_latest=True, prompt="Hello world. Goodbye world.")

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_prompts/name/multi-edit/",
            data={
                "edits": [
                    {"old": "Hello world", "new": "Hi there"},
                    {"old": "Goodbye world", "new": "See you later"},
                ],
                "base_version": 1,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        latest = LLMPrompt.objects.get(team=self.team, name="multi-edit", version=2, deleted=False)
        assert latest.prompt == "Hi there. See you later."

    @parameterized.expand(
        [
            (
                "old_not_found",
                "Hello world.",
                [{"old": "nonexistent text", "new": "replacement"}],
                "not found",
                0,
            ),
            (
                "ambiguous_match",
                "foo bar foo",
                [{"old": "foo", "new": "baz"}],
                "matches 2 times",
                0,
            ),
        ]
    )
    def test_update_prompt_by_name_with_edits_rejects_bad_edit(
        self, mock_feature_enabled, _name, prompt, edits, expected_detail, expected_index
    ):
        self.create_prompt_version(name="edit-error", version=1, is_latest=True, prompt=prompt)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_prompts/name/edit-error/",
            data={"edits": edits, "base_version": 1},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert expected_detail in response.json()["detail"]
        assert response.json()["edit_index"] == expected_index

    @parameterized.expand(
        [
            (
                "both_provided",
                {"prompt": "v2", "edits": [{"old": "v1", "new": "v2"}], "base_version": 1},
            ),
            (
                "neither_provided",
                {"base_version": 1},
            ),
        ]
    )
    def test_update_prompt_by_name_rejects_invalid_prompt_edits_combo(self, mock_feature_enabled, _name, data):
        self.create_prompt_version(name="combo-edit", version=1, is_latest=True, prompt="v1")

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_prompts/name/combo-edit/",
            data=data,
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_update_prompt_by_name_with_edits_rejects_oversized_result(self, mock_feature_enabled):
        self.create_prompt_version(name="size-edit", version=1, is_latest=True, prompt="small")

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_prompts/name/size-edit/",
            data={
                "edits": [{"old": "small", "new": "x" * (MAX_PROMPT_PAYLOAD_BYTES + 1)}],
                "base_version": 1,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "size limit" in response.json()["detail"]

    def test_update_prompt_by_name_with_edits_on_json_prompt(self, mock_feature_enabled):
        self.create_prompt_version(
            name="json-edit",
            version=1,
            is_latest=True,
            prompt={"system": "You are helpful.", "temperature": 0.7},
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_prompts/name/json-edit/",
            data={
                "edits": [{"old": "You are helpful.", "new": "You are an expert."}],
                "base_version": 1,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        latest = LLMPrompt.objects.get(team=self.team, name="json-edit", version=2, deleted=False)
        assert latest.prompt == {"system": "You are an expert.", "temperature": 0.7}

    def test_update_prompt_by_name_forbidden_for_personal_api_key_auth(self, mock_feature_enabled):
        self.create_prompt_version(name="publish-prompt", version=1, is_latest=True, prompt="v1")
        api_key = self.create_personal_api_key_with_scopes(["llm_prompt:read"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")

        read_response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/name/publish-prompt/")
        write_response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_prompts/name/publish-prompt/",
            data={"prompt": "v2", "base_version": 1},
            format="json",
        )

        assert read_response.status_code == status.HTTP_200_OK
        assert write_response.status_code == status.HTTP_403_FORBIDDEN

    def test_resolve_prompt_by_name_returns_selected_prompt_and_versions(self, mock_feature_enabled):
        historical = self.create_prompt_version(name="versions-prompt", version=1, is_latest=False, prompt="v1")
        latest = self.create_prompt_version(name="versions-prompt", version=2, is_latest=True, prompt="v2")

        response = self.client.get(
            f"/api/environments/{self.team.id}/llm_prompts/resolve/name/versions-prompt/?version=1"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["prompt"]["id"] == str(historical.id)
        assert data["prompt"]["version"] == 1
        assert data["prompt"]["latest_version"] == 2
        assert [prompt["version"] for prompt in data["versions"]] == [2, 1]
        assert data["versions"][0]["id"] == str(latest.id)
        assert data["versions"][0]["is_latest"] is True
        assert data["has_more"] is False

    def test_resolve_prompt_by_name_supports_paged_versions_with_has_more(self, mock_feature_enabled):
        for version in range(1, 4):
            self.create_prompt_version(
                name="paged-prompt",
                version=version,
                prompt=f"v{version}",
                is_latest=version == 3,
            )

        response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/resolve/name/paged-prompt/?limit=2")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert [prompt["version"] for prompt in data["versions"]] == [3, 2]
        assert data["has_more"] is True

    def test_resolve_prompt_by_name_keeps_versions_page_order_and_limit_for_old_selected_version(
        self, mock_feature_enabled
    ):
        selected = None
        for version in range(1, 5):
            prompt = self.create_prompt_version(
                name="paged-prompt",
                version=version,
                prompt=f"v{version}",
                is_latest=version == 4,
            )
            if version == 1:
                selected = prompt

        response = self.client.get(
            f"/api/environments/{self.team.id}/llm_prompts/resolve/name/paged-prompt/?version=1&limit=2"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["prompt"]["version"] == 1
        assert selected is not None
        assert data["prompt"]["id"] == str(selected.id)
        assert [prompt["version"] for prompt in data["versions"]] == [4, 3]
        assert len(data["versions"]) == 2
        assert data["has_more"] is True

    def test_resolve_prompt_by_name_supports_before_version_cursor(self, mock_feature_enabled):
        for version in range(1, 4):
            self.create_prompt_version(
                name="paged-prompt",
                version=version,
                prompt=f"v{version}",
                is_latest=version == 3,
            )

        response = self.client.get(
            f"/api/environments/{self.team.id}/llm_prompts/resolve/name/paged-prompt/?before_version=2&limit=2"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert [prompt["version"] for prompt in data["versions"]] == [1]
        assert data["has_more"] is False

    def test_resolve_prompt_by_name_rejects_offset_with_before_version(self, mock_feature_enabled):
        self.create_prompt_version(name="paged-prompt", version=1, prompt="v1", is_latest=True)

        response = self.client.get(
            f"/api/environments/{self.team.id}/llm_prompts/resolve/name/paged-prompt/?offset=0&before_version=1"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "offset or before_version" in response.json()["detail"]

    def test_archive_endpoint_archives_all_active_versions_for_name(self, mock_feature_enabled):
        self.create_prompt_version(name="archive-prompt", version=1, is_latest=False, prompt="v1")
        self.create_prompt_version(name="archive-prompt", version=2, is_latest=True, prompt="v2")

        response = self.client.post(f"/api/environments/{self.team.id}/llm_prompts/name/archive-prompt/archive/")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert LLMPrompt.objects.filter(team=self.team, name="archive-prompt", deleted=False).count() == 0

        recreate_response = self.client.post(
            f"/api/environments/{self.team.id}/llm_prompts/",
            data={"name": "archive-prompt", "prompt": "fresh"},
            format="json",
        )

        assert recreate_response.status_code == status.HTTP_201_CREATED
        assert recreate_response.json()["version"] == 1

    def test_archive_endpoint_invalidates_latest_and_version_fetches(self, mock_feature_enabled):
        self.create_prompt_version(name="archive-prompt", version=1, is_latest=False, prompt="v1")
        self.create_prompt_version(name="archive-prompt", version=2, is_latest=True, prompt="v2")

        with patch("posthog.api.services.llm_prompt.transaction.on_commit", side_effect=lambda callback: callback()):
            first_latest = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/name/archive-prompt/")
            first_version = self.client.get(
                f"/api/environments/{self.team.id}/llm_prompts/name/archive-prompt/?version=1"
            )
            archive_response = self.client.post(
                f"/api/environments/{self.team.id}/llm_prompts/name/archive-prompt/archive/"
            )

        assert first_latest.status_code == status.HTTP_200_OK
        assert first_version.status_code == status.HTTP_200_OK
        assert archive_response.status_code == status.HTTP_204_NO_CONTENT

        second_latest = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/name/archive-prompt/")
        second_version = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/name/archive-prompt/?version=1")

        assert second_latest.status_code == status.HTTP_404_NOT_FOUND
        assert second_version.status_code == status.HTTP_404_NOT_FOUND

    @override_settings(TEST=False)
    def test_archive_endpoint_batches_version_cache_invalidation_when_many_versions_exist(self, mock_feature_enabled):
        for version in range(1, 106):
            self.create_prompt_version(
                name="archive-prompt",
                version=version,
                is_latest=version == 105,
                prompt=f"v{version}",
            )

        with (
            patch("posthog.api.services.llm_prompt.transaction.on_commit", side_effect=lambda callback: callback()),
            patch("posthog.api.services.llm_prompt.invalidate_prompt_latest_cache") as mock_invalidate_latest,
            patch("posthog.api.services.llm_prompt.invalidate_prompt_version_caches") as mock_invalidate_versions,
            patch("posthog.tasks.llm_prompt_cache.invalidate_archived_prompt_versions_cache_task.delay") as mock_delay,
        ):
            response = self.client.post(f"/api/environments/{self.team.id}/llm_prompts/name/archive-prompt/archive/")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_invalidate_latest.assert_called_once_with(self.team.id, "archive-prompt")
        assert mock_invalidate_versions.call_count == 1
        invalidated_versions = mock_invalidate_versions.call_args.args[2]
        assert invalidated_versions == list(range(1, 101))
        mock_delay.assert_called_once_with(self.team.id, "archive-prompt", 101, 105)

    def test_resolve_prompt_by_name_supports_explicit_version_for_session_auth(self, mock_feature_enabled):
        historical = self.create_prompt_version(name="resolve-prompt", version=1, is_latest=False, prompt="v1")
        self.create_prompt_version(name="resolve-prompt", version=2, is_latest=True, prompt="v2")

        response = self.client.get(
            f"/api/environments/{self.team.id}/llm_prompts/resolve/name/resolve-prompt/?version=1"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["prompt"]["id"] == str(historical.id)
        assert response.json()["prompt"]["version"] == 1
        assert "created_by" in response.json()["prompt"]

    def test_resolve_prompt_by_name_supports_exact_version_id_for_session_auth(self, mock_feature_enabled):
        historical = self.create_prompt_version(name="resolve-prompt", version=1, is_latest=False, prompt="v1")
        self.create_prompt_version(name="resolve-prompt", version=2, is_latest=True, prompt="v2")

        response = self.client.get(
            f"/api/environments/{self.team.id}/llm_prompts/resolve/name/resolve-prompt/"
            f"?version=1&version_id={historical.id}"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["prompt"]["id"] == str(historical.id)
        assert response.json()["prompt"]["version"] == 1

    def test_resolve_prompt_by_name_returns_404_for_archived_version_id_after_name_reuse(self, mock_feature_enabled):
        historical = self.create_prompt_version(name="resolve-prompt", version=1, is_latest=True, prompt="old")
        LLMPrompt.objects.filter(team=self.team, name="resolve-prompt", deleted=False).update(
            deleted=True,
            is_latest=False,
        )
        self.create_prompt_version(name="resolve-prompt", version=1, is_latest=True, prompt="new")

        response = self.client.get(
            f"/api/environments/{self.team.id}/llm_prompts/resolve/name/resolve-prompt/"
            f"?version=1&version_id={historical.id}"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_resolve_prompt_by_name_allowed_for_personal_api_key_auth(self, mock_feature_enabled):
        self.create_prompt_version(name="test-prompt")

        api_key = self.create_personal_api_key_with_scopes(["llm_prompt:read"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")

        response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/resolve/name/test-prompt/")

        assert response.status_code == status.HTTP_200_OK

    @override_settings(TEST=False)
    @patch("posthog.api.llm_prompt.capture_internal")
    def test_fetch_prompt_by_name_emits_version_metadata(self, mock_capture_internal, mock_feature_enabled):
        self.create_prompt_version(name="test-prompt", version=1, is_latest=False, prompt="v1")
        latest = self.create_prompt_version(name="test-prompt", version=2, is_latest=True, prompt="v2")

        response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/name/test-prompt/")

        assert response.status_code == status.HTTP_200_OK
        mock_capture_internal.assert_called_once()
        properties = mock_capture_internal.call_args.kwargs["properties"]
        assert properties["prompt_id"] == str(latest.id)
        assert properties["prompt_name"] == "test-prompt"
        assert properties["prompt_version"] == 2
        assert properties["prompt_is_latest"] is True
        assert properties["prompt_first_version_created_at"] == response.json()["first_version_created_at"]

    def test_fetch_prompt_by_name_not_found(self, mock_feature_enabled):
        response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/name/non-existent/")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "not found" in response.json()["detail"].lower()

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

    def test_create_prompt_with_reserved_name_new_fails(self, mock_feature_enabled):
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_prompts/",
            data={"name": "new", "prompt": "Content"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "name"
        assert "'new' is a reserved name" in response.json()["detail"]

    def test_create_prompt_with_invalid_name_fails(self, mock_feature_enabled):
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_prompts/",
            data={"name": "invalid name with spaces", "prompt": "Content"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "name"
        assert "Only letters, numbers, hyphens (-) and underscores (_) are allowed" in response.json()["detail"]

    def test_returns_403_when_feature_flag_disabled(self, mock_class_feature_enabled):
        mock_class_feature_enabled.return_value = False
        self.create_prompt_version(name="test-prompt")

        response = self.client.get(f"/api/environments/{self.team.id}/llm_prompts/name/test-prompt/")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_get_by_name_patch_uses_write_scope(self, mock_feature_enabled):
        request = APIRequestFactory().patch("/api/environments/1/llm_prompts/name/example/")
        view = LLMPromptViewSet()
        view.action = "get_by_name"
        assert view.dangerously_get_required_scopes(request, view) == ["llm_prompt:write"]

        view.action = "update_by_name"
        assert view.dangerously_get_required_scopes(request, view) == ["llm_prompt:write"]

    def test_update_by_name_uses_publish_specific_burst_throttle(self, mock_feature_enabled):
        view = LLMPromptViewSet()
        view.action = "update_by_name"

        throttles = view.get_throttles()

        assert isinstance(throttles[0], LLMPromptPublishBurstRateThrottle)
        assert isinstance(throttles[1], BurstRateThrottle)
        assert isinstance(throttles[2], SustainedRateThrottle)

    def test_get_by_name_uses_default_burst_and_sustained_throttles(self, mock_feature_enabled):
        view = LLMPromptViewSet()
        view.action = "get_by_name"

        throttles = view.get_throttles()

        assert len(throttles) == 2
        assert isinstance(throttles[0], BurstRateThrottle)
        assert isinstance(throttles[1], SustainedRateThrottle)

    def test_duplicate_prompt_creates_new_prompt_with_latest_content(self, mock_feature_enabled):
        self.create_prompt_version(name="original", version=1, is_latest=False, prompt="v1")
        self.create_prompt_version(name="original", version=2, is_latest=True, prompt="v2-latest")

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_prompts/name/original/duplicate/",
            data={"new_name": "copy-of-original"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["name"] == "copy-of-original"
        assert data["prompt"] == "v2-latest"
        assert data["version"] == 1
        assert data["is_latest"] is True
        assert data["latest_version"] == 1
        assert data["version_count"] == 1

    def test_duplicate_prompt_returns_404_for_nonexistent_source(self, mock_feature_enabled):
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_prompts/name/nonexistent/duplicate/",
            data={"new_name": "copy"},
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_duplicate_prompt_returns_400_when_target_name_already_exists(self, mock_feature_enabled):
        self.create_prompt_version(name="original", version=1, is_latest=True, prompt="content")
        self.create_prompt_version(name="taken-name", version=1, is_latest=True, prompt="other")

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_prompts/name/original/duplicate/",
            data={"new_name": "taken-name"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "already exists" in response.json()["detail"]

    @parameterized.expand(
        [
            ("spaces", "invalid name with spaces"),
            ("slash", "has/slash"),
            ("dot", "has.dot"),
            ("reserved_new", "new"),
            ("reserved_new_upper", "NEW"),
        ]
    )
    def test_duplicate_prompt_rejects_invalid_new_name(self, mock_feature_enabled, _label, bad_name):
        self.create_prompt_version(name="original", version=1, is_latest=True, prompt="content")

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_prompts/name/original/duplicate/",
            data={"new_name": bad_name},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_duplicate_prompt_does_not_affect_source_prompt(self, mock_feature_enabled):
        self.create_prompt_version(name="original", version=1, is_latest=True, prompt="content")

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_prompts/name/original/duplicate/",
            data={"new_name": "copy"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        source = LLMPrompt.objects.get(team=self.team, name="original", deleted=False)
        assert source.is_latest is True
        assert source.prompt == "content"

    def test_duplicate_prompt_allows_reuse_of_archived_name(self, mock_feature_enabled):
        self.create_prompt_version(name="original", version=1, is_latest=True, prompt="content")
        self.create_prompt_version(name="archived-name", version=1, is_latest=False, deleted=True)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_prompts/name/original/duplicate/",
            data={"new_name": "archived-name"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["name"] == "archived-name"
        assert response.json()["version"] == 1
