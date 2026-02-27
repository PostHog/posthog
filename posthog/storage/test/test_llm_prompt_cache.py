from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.api.llm_prompt import LLMPromptSerializer
from posthog.models.llm_prompt import LLMPrompt
from posthog.storage.llm_prompt_cache import (
    _serialize_prompt,
    get_prompt_by_name_from_cache,
    invalidate_team_prompt_cache,
    llm_prompts_hypercache,
)


class TestLLMPromptCache(BaseTest):
    def setUp(self):
        super().setUp()
        llm_prompts_hypercache.clear_cache(self.team)

    def tearDown(self):
        llm_prompts_hypercache.clear_cache(self.team)
        super().tearDown()

    def test_get_prompt_by_name_from_cache_returns_serialized_prompt(self):
        prompt = LLMPrompt.objects.create(
            team=self.team,
            name="cached-prompt",
            prompt="You are a helpful assistant.",
            created_by=self.user,
        )

        cached_prompt = get_prompt_by_name_from_cache(self.team, "cached-prompt")

        self.assertIsNotNone(cached_prompt)
        assert cached_prompt is not None
        self.assertEqual(cached_prompt["id"], str(prompt.id))
        self.assertEqual(cached_prompt["name"], prompt.name)
        self.assertEqual(cached_prompt["prompt"], prompt.prompt)
        self.assertEqual(cached_prompt["version"], prompt.version)
        self.assertEqual(cached_prompt["deleted"], prompt.deleted)
        self.assertNotIn("created_by", cached_prompt)

    def test_serialize_prompt_matches_api_serializer_keys_except_created_by(self):
        prompt = LLMPrompt.objects.create(
            team=self.team,
            name="serializer-shape",
            prompt="Prompt content",
            created_by=self.user,
        )

        serialized_prompt = _serialize_prompt(prompt)
        serializer_keys = set(LLMPromptSerializer(prompt).data.keys())
        expected_keys = serializer_keys - {"created_by"}

        self.assertEqual(set(serialized_prompt.keys()), expected_keys)

    def test_get_prompt_by_name_from_cache_returns_none_for_missing_prompt_name(self):
        LLMPrompt.objects.create(
            team=self.team,
            name="existing-prompt",
            prompt="Prompt content",
            created_by=self.user,
        )

        cached_prompt = get_prompt_by_name_from_cache(self.team, "missing-prompt")

        self.assertIsNone(cached_prompt)

    def test_get_prompt_by_name_from_cache_hits_loader_once_when_cache_is_warm(self):
        LLMPrompt.objects.create(
            team=self.team,
            name="cached-prompt",
            prompt="Prompt content",
            created_by=self.user,
        )

        with patch.object(llm_prompts_hypercache, "load_fn", wraps=llm_prompts_hypercache.load_fn) as mock_load_fn:
            get_prompt_by_name_from_cache(self.team, "cached-prompt")
            get_prompt_by_name_from_cache(self.team, "cached-prompt")

        self.assertEqual(mock_load_fn.call_count, 1)

    def test_invalidate_team_prompt_cache_forces_loader_on_next_read(self):
        LLMPrompt.objects.create(
            team=self.team,
            name="cached-prompt",
            prompt="Prompt content",
            created_by=self.user,
        )

        with patch.object(llm_prompts_hypercache, "load_fn", wraps=llm_prompts_hypercache.load_fn) as mock_load_fn:
            get_prompt_by_name_from_cache(self.team, "cached-prompt")
            invalidate_team_prompt_cache(self.team.id)
            get_prompt_by_name_from_cache(self.team, "cached-prompt")

        self.assertEqual(mock_load_fn.call_count, 2)

    def test_name_miss_falls_back_to_db_when_cached_map_is_stale(self):
        LLMPrompt.objects.create(
            team=self.team,
            name="existing-prompt",
            prompt="Prompt content",
            created_by=self.user,
        )
        get_prompt_by_name_from_cache(self.team, "existing-prompt")

        with patch("posthog.models.llm_prompt.transaction.on_commit", side_effect=lambda callback: None):
            LLMPrompt.objects.create(
                team=self.team,
                name="new-prompt",
                prompt="New prompt content",
                created_by=self.user,
            )

        with patch("posthog.storage.llm_prompt_cache.invalidate_team_prompt_cache") as mock_invalidate:
            cached_prompt = get_prompt_by_name_from_cache(self.team, "new-prompt")

        self.assertIsNotNone(cached_prompt)
        assert cached_prompt is not None
        self.assertEqual(cached_prompt["name"], "new-prompt")
        self.assertEqual(cached_prompt["prompt"], "New prompt content")
        mock_invalidate.assert_called_with(self.team.id)

    def test_name_miss_fallback_still_returns_prompt_when_invalidation_fails(self):
        LLMPrompt.objects.create(
            team=self.team,
            name="existing-prompt",
            prompt="Prompt content",
            created_by=self.user,
        )
        get_prompt_by_name_from_cache(self.team, "existing-prompt")

        with patch("posthog.models.llm_prompt.transaction.on_commit", side_effect=lambda callback: None):
            LLMPrompt.objects.create(
                team=self.team,
                name="new-prompt",
                prompt="New prompt content",
                created_by=self.user,
            )

        with (
            patch(
                "posthog.storage.llm_prompt_cache.invalidate_team_prompt_cache",
                side_effect=Exception("cache clear failed"),
            ),
            patch("posthog.storage.llm_prompt_cache.capture_exception") as mock_capture_exception,
        ):
            cached_prompt = get_prompt_by_name_from_cache(self.team, "new-prompt")

        self.assertIsNotNone(cached_prompt)
        assert cached_prompt is not None
        self.assertEqual(cached_prompt["name"], "new-prompt")
        mock_capture_exception.assert_called_once()


class TestLLMPromptCacheSignals(BaseTest):
    def test_model_signal_invalidates_cache_on_commit_with_team_id(self):
        with (
            patch("posthog.models.llm_prompt.transaction.on_commit") as mock_on_commit,
            patch("posthog.storage.llm_prompt_cache.invalidate_team_prompt_cache") as mock_invalidate,
        ):
            mock_on_commit.side_effect = lambda callback: callback()

            LLMPrompt.objects.create(
                team=self.team,
                name="signal-prompt",
                prompt="Prompt content",
                created_by=self.user,
            )

        self.assertTrue(mock_on_commit.called)
        mock_invalidate.assert_called_with(self.team.id)
