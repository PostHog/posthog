from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from posthog.models.llm_prompt import LLMPrompt
from posthog.storage.llm_prompt_cache import (
    _serialize_prompt,
    get_prompt_by_name_from_cache,
    invalidate_prompt_latest_cache,
    invalidate_prompt_name_caches,
    invalidate_prompt_version_cache,
    llm_prompts_hypercache,
)
from posthog.storage.llm_prompt_cache_keys import prompt_latest_cache_key


class TestLLMPromptCache(BaseTest):
    version_cache_names = ["cached-prompt", "existing-prompt", "new-prompt", "reused-prompt", "serializer-shape"]

    def setUp(self):
        super().setUp()
        self._clear_known_latest_cache_keys()
        self._clear_known_version_cache_keys()

    def tearDown(self):
        self._clear_known_latest_cache_keys()
        self._clear_known_version_cache_keys()
        super().tearDown()

    def create_prompt_version(
        self,
        *,
        name: str = "cached-prompt",
        prompt: str = "Prompt content",
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

    def clear_version_cache(self, prompt_name: str, version: int) -> None:
        invalidate_prompt_version_cache(self.team.id, prompt_name, version)

    def _clear_known_version_cache_keys(self) -> None:
        for prompt_name in self.version_cache_names:
            for version in range(1, 4):
                invalidate_prompt_version_cache(self.team.id, prompt_name, version)

    def _clear_known_latest_cache_keys(self) -> None:
        for prompt_name in self.version_cache_names:
            invalidate_prompt_latest_cache(self.team.id, prompt_name)

    def test_get_prompt_by_name_from_cache_returns_latest_prompt_with_version_history_metadata(self):
        first_version = self.create_prompt_version(name="cached-prompt", version=1, is_latest=False, prompt="v1")
        latest_version = self.create_prompt_version(name="cached-prompt", version=2, is_latest=True, prompt="v2")

        cached_prompt = get_prompt_by_name_from_cache(self.team, "cached-prompt")

        assert cached_prompt is not None
        self.assertEqual(cached_prompt["id"], str(latest_version.id))
        self.assertEqual(cached_prompt["version"], 2)
        self.assertEqual(cached_prompt["latest_version"], 2)
        self.assertEqual(cached_prompt["version_count"], 2)
        self.assertEqual(
            cached_prompt["first_version_created_at"], first_version.created_at.isoformat().replace("+00:00", "Z")
        )
        self.assertTrue(cached_prompt["is_latest"])

    def test_get_prompt_by_name_from_cache_returns_historical_prompt_with_latest_metadata(self):
        historical = self.create_prompt_version(name="cached-prompt", version=1, is_latest=False, prompt="v1")
        self.create_prompt_version(name="cached-prompt", version=2, is_latest=True, prompt="v2")

        cached_prompt = get_prompt_by_name_from_cache(self.team, "cached-prompt", version=1)

        assert cached_prompt is not None
        self.assertEqual(cached_prompt["id"], str(historical.id))
        self.assertEqual(cached_prompt["version"], 1)
        self.assertEqual(cached_prompt["latest_version"], 2)
        self.assertEqual(cached_prompt["version_count"], 2)
        self.assertFalse(cached_prompt["is_latest"])

    def test_first_version_created_at_follows_version_one_not_oldest_timestamp(self):
        version_one = self.create_prompt_version(name="cached-prompt", version=1, is_latest=False, prompt="v1")
        version_two = self.create_prompt_version(name="cached-prompt", version=2, is_latest=True, prompt="v2")

        LLMPrompt.objects.filter(pk=version_one.pk).update(created_at=timezone.now())
        LLMPrompt.objects.filter(pk=version_two.pk).update(created_at=timezone.now() - timedelta(days=1))

        version_one.refresh_from_db()
        cached_prompt = get_prompt_by_name_from_cache(self.team, "cached-prompt")

        assert cached_prompt is not None
        self.assertEqual(
            cached_prompt["first_version_created_at"], version_one.created_at.isoformat().replace("+00:00", "Z")
        )

    def test_serialize_prompt_matches_expected_cache_shape(self):
        prompt = self.create_prompt_version(name="serializer-shape")

        serialized_prompt = _serialize_prompt(prompt)
        self.assertEqual(
            set(serialized_prompt.keys()),
            {
                "id",
                "name",
                "prompt",
                "version",
                "created_at",
                "updated_at",
                "deleted",
                "is_latest",
                "latest_version",
                "version_count",
                "first_version_created_at",
            },
        )

    def test_get_prompt_by_name_from_cache_hits_latest_loader_once_when_cache_is_warm(self):
        self.create_prompt_version(name="cached-prompt", version=1, is_latest=True)

        with patch.object(llm_prompts_hypercache, "load_fn", wraps=llm_prompts_hypercache.load_fn) as mock_load_fn:
            get_prompt_by_name_from_cache(self.team, "cached-prompt")
            get_prompt_by_name_from_cache(self.team, "cached-prompt")

        self.assertEqual(mock_load_fn.call_count, 1)

    def test_get_prompt_by_name_from_cache_hits_version_loader_once_when_historical_cache_is_warm(self):
        self.create_prompt_version(name="cached-prompt", version=1, is_latest=False, prompt="v1")
        self.create_prompt_version(name="cached-prompt", version=2, is_latest=True, prompt="v2")
        get_prompt_by_name_from_cache(self.team, "cached-prompt")

        with patch.object(
            llm_prompts_hypercache,
            "load_fn",
            wraps=llm_prompts_hypercache.load_fn,
        ) as mock_load_fn:
            get_prompt_by_name_from_cache(self.team, "cached-prompt", version=1)
            get_prompt_by_name_from_cache(self.team, "cached-prompt", version=1)

        self.assertEqual(mock_load_fn.call_count, 1)

    def test_invalidate_prompt_latest_cache_forces_latest_loader_on_next_read(self):
        self.create_prompt_version(name="cached-prompt", version=1, is_latest=True)

        with patch.object(llm_prompts_hypercache, "load_fn", wraps=llm_prompts_hypercache.load_fn) as mock_load_fn:
            get_prompt_by_name_from_cache(self.team, "cached-prompt")
            invalidate_prompt_latest_cache(self.team.id, "cached-prompt")
            get_prompt_by_name_from_cache(self.team, "cached-prompt")

        self.assertEqual(mock_load_fn.call_count, 2)

    def test_invalidate_prompt_version_cache_forces_version_loader_on_next_read(self):
        self.create_prompt_version(name="cached-prompt", version=1, is_latest=False, prompt="v1")
        self.create_prompt_version(name="cached-prompt", version=2, is_latest=True, prompt="v2")
        get_prompt_by_name_from_cache(self.team, "cached-prompt")

        with patch.object(
            llm_prompts_hypercache,
            "load_fn",
            wraps=llm_prompts_hypercache.load_fn,
        ) as mock_load_fn:
            get_prompt_by_name_from_cache(self.team, "cached-prompt", version=1)
            invalidate_prompt_version_cache(self.team.id, "cached-prompt", 1)
            get_prompt_by_name_from_cache(self.team, "cached-prompt", version=1)

        self.assertEqual(mock_load_fn.call_count, 2)

    def test_name_miss_falls_back_to_db_when_latest_prompt_cache_entry_is_stale(self):
        self.create_prompt_version(name="existing-prompt", version=1, is_latest=True)
        get_prompt_by_name_from_cache(self.team, "existing-prompt")

        with patch("posthog.models.llm_prompt.transaction.on_commit", side_effect=lambda callback: None):
            self.create_prompt_version(name="new-prompt", version=1, is_latest=True)

        cached_prompt = get_prompt_by_name_from_cache(self.team, "new-prompt")

        assert cached_prompt is not None
        self.assertEqual(cached_prompt["name"], "new-prompt")
        self.assertEqual(cached_prompt["version"], 1)

    def test_archive_invalidation_clears_sparse_version_cache_for_reused_name(self):
        old_v1 = self.create_prompt_version(name="reused-prompt", version=1, is_latest=False, prompt="old-v1")
        self.create_prompt_version(name="reused-prompt", version=2, is_latest=True, prompt="old-v2")
        first_cached = get_prompt_by_name_from_cache(self.team, "reused-prompt", version=1)
        assert first_cached is not None
        self.assertEqual(first_cached["id"], str(old_v1.id))

        invalidate_prompt_name_caches(self.team.id, "reused-prompt", [1, 2])
        LLMPrompt.objects.filter(team=self.team, name="reused-prompt", deleted=False).update(
            deleted=True,
            is_latest=False,
        )

        new_v1 = self.create_prompt_version(name="reused-prompt", version=1, is_latest=True, prompt="new-v1")
        second_cached = get_prompt_by_name_from_cache(self.team, "reused-prompt", version=1)

        assert second_cached is not None
        self.assertEqual(second_cached["id"], str(new_v1.id))
        self.assertNotEqual(second_cached["id"], str(old_v1.id))

    def test_stale_exact_version_cache_entry_is_detected_using_first_version_id(self):
        old_v1 = self.create_prompt_version(name="reused-prompt", version=1, is_latest=True, prompt="old-v1")
        cached_old = get_prompt_by_name_from_cache(self.team, "reused-prompt", version=1)
        assert cached_old is not None
        self.assertEqual(cached_old["id"], str(old_v1.id))

        with patch("posthog.models.llm_prompt.transaction.on_commit", side_effect=lambda callback: None):
            LLMPrompt.objects.filter(team=self.team, name="reused-prompt", deleted=False).update(
                deleted=True, is_latest=False
            )
            new_v1 = self.create_prompt_version(name="reused-prompt", version=1, is_latest=True, prompt="new-v1")

        invalidate_prompt_latest_cache(self.team.id, "reused-prompt")
        refreshed = get_prompt_by_name_from_cache(self.team, "reused-prompt", version=1)

        assert refreshed is not None
        self.assertEqual(refreshed["id"], str(new_v1.id))
        self.assertNotEqual(refreshed["id"], str(old_v1.id))

    def test_stale_exact_version_cache_entry_uses_first_version_id_generation_marker(self):
        old_v1 = self.create_prompt_version(name="reused-prompt", version=1, is_latest=True, prompt="old-v1")
        LLMPrompt.objects.filter(pk=old_v1.pk).update(created_at=datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC))

        cached_old = get_prompt_by_name_from_cache(self.team, "reused-prompt", version=1)
        assert cached_old is not None
        self.assertEqual(cached_old["id"], str(old_v1.id))

        with patch("posthog.models.llm_prompt.transaction.on_commit", side_effect=lambda callback: None):
            LLMPrompt.objects.filter(team=self.team, name="reused-prompt", deleted=False).update(
                deleted=True,
                is_latest=False,
            )
            new_v1 = self.create_prompt_version(name="reused-prompt", version=1, is_latest=True, prompt="new-v1")

        LLMPrompt.objects.filter(pk=new_v1.pk).update(created_at=datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC))
        invalidate_prompt_latest_cache(self.team.id, "reused-prompt")

        refreshed = get_prompt_by_name_from_cache(self.team, "reused-prompt", version=1)
        assert refreshed is not None
        self.assertEqual(refreshed["id"], str(new_v1.id))
        self.assertNotEqual(refreshed["id"], str(old_v1.id))

    def test_exact_fetch_refreshes_latest_cache_entry_missing_generation_marker(self):
        self.create_prompt_version(name="cached-prompt", version=1, is_latest=False, prompt="v1")
        self.create_prompt_version(name="cached-prompt", version=2, is_latest=True, prompt="v2")

        latest_key = prompt_latest_cache_key(self.team.id, "cached-prompt")
        latest_entry = llm_prompts_hypercache.get_from_cache(latest_key)
        assert isinstance(latest_entry, dict)

        stale_latest_entry = dict(latest_entry)
        stale_latest_entry.pop("_first_version_id", None)
        llm_prompts_hypercache.set_cache_value(latest_key, stale_latest_entry)

        historical = get_prompt_by_name_from_cache(self.team, "cached-prompt", version=1)
        assert historical is not None

        refreshed_latest_entry = llm_prompts_hypercache.get_from_cache(latest_key)
        assert isinstance(refreshed_latest_entry, dict)
        assert "_first_version_id" in refreshed_latest_entry


class TestLLMPromptCacheSignals(BaseTest):
    def test_model_signal_invalidates_latest_and_exact_version_caches_on_commit(self):
        with (
            patch("posthog.models.llm_prompt.transaction.on_commit") as mock_on_commit,
            patch("posthog.storage.llm_prompt_cache.invalidate_prompt_latest_cache") as mock_invalidate_latest,
            patch("posthog.storage.llm_prompt_cache.invalidate_prompt_version_cache") as mock_invalidate_version,
        ):
            mock_on_commit.side_effect = lambda callback: callback()

            LLMPrompt.objects.create(
                team=self.team,
                name="signal-prompt",
                prompt="Prompt content",
                created_by=self.user,
            )

        self.assertTrue(mock_on_commit.called)
        mock_invalidate_latest.assert_called_with(self.team.id, "signal-prompt")
        mock_invalidate_version.assert_called_with(self.team.id, "signal-prompt", 1)
