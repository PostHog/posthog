import threading
from concurrent.futures import Future

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.llm import managed_decision_model
from posthog.llm.managed_decision_model import (
    DEFAULT_DECISION_MODEL,
    BackgroundRefresher,
    ManagedDecisionModel,
    model_from_config,
)
from posthog.storage.llm_prompt_cache import invalidate_prompt_label_cache, invalidate_prompt_latest_cache
from posthog.storage.llm_prompt_cache_keys import prompt_label_cache_key
from posthog.utils import safe_cache_delete

from products.ai_observability.backend.models.llm_prompt import LLMPrompt, LLMPromptLabel

NEW_MODEL = "posthog/hogference/jeeves-0.1"


class TestBackgroundRefresher(SimpleTestCase):
    def test_a_request_never_waits_for_the_fetch(self) -> None:
        release = threading.Event()
        fetches: list[Future] = []

        def slow_fetch() -> str:
            assert release.wait(timeout=5)
            return "managed"

        refresher = BackgroundRefresher("test-prompt", "bundled", slow_fetch)
        submit = refresher._executor.submit
        with patch.object(refresher._executor, "submit", side_effect=lambda fn: fetches.append(submit(fn))):
            assert refresher.current() == "bundled"
            assert refresher.current() == "bundled"
            release.set()
            fetches[0].result(timeout=5)

            assert refresher.current() == "managed"
            assert len(fetches) == 1

    @parameterized.expand(
        [
            ("first_fetch_fails", [ConnectionError("unavailable")], "bundled"),
            ("later_fetch_fails", ["managed", ConnectionError("unavailable")], "managed"),
        ]
    )
    def test_a_failed_fetch_keeps_the_last_value(self, _name: str, fetches: list, expected: str) -> None:
        results = iter(fetches)

        def fetch() -> str:
            result = next(results)
            if isinstance(result, Exception):
                raise result
            return result

        refresher = BackgroundRefresher("test-prompt", "bundled", fetch)
        for _ in fetches:
            refresher._refresh()

        assert refresher.current() == expected


class TestModelConfig(SimpleTestCase):
    @parameterized.expand(
        [
            ("valid", {"model": NEW_MODEL}, NEW_MODEL),
            ("missing", {}, DEFAULT_DECISION_MODEL),
            ("wrong_type", {"model": 1}, DEFAULT_DECISION_MODEL),
            ("empty", {"model": ""}, DEFAULT_DECISION_MODEL),
            ("whitespace", {"model": "model\nother"}, DEFAULT_DECISION_MODEL),
        ]
    )
    def test_model_config(self, _name: str, config: dict, expected: str) -> None:
        assert model_from_config(config) == expected


class TestGetAppPromptFromDatabase(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(override_settings(CLOUD_DEPLOYMENT="US"))
        self.enterContext(patch.object(managed_decision_model, "POSTHOG_PROMPTS_TEAM_ID", self.team.id))
        self._clear_caches()
        self.addCleanup(self._clear_caches)

    def _clear_caches(self) -> None:
        invalidate_prompt_latest_cache(self.team.id, "emoji-search-suggestions")
        invalidate_prompt_label_cache(self.team.id, "emoji-search-suggestions", "production")
        safe_cache_delete(prompt_label_cache_key(self.team.id, "emoji-search-suggestions", "production"))

    def _publish_prompt(self, *, version: int, config: dict) -> None:
        LLMPrompt.objects.filter(team=self.team, name="emoji-search-suggestions").update(is_latest=False)
        LLMPrompt.objects.create(
            team=self.team,
            name="emoji-search-suggestions",
            prompt="Suggest related emojis for a search.",
            version=version,
            is_latest=True,
            config=config,
            created_by=self.user,
        )

    def _label_production(self, version: int) -> None:
        LLMPromptLabel.objects.create(
            team=self.team,
            prompt_name="emoji-search-suggestions",
            name="production",
            prompt=LLMPrompt.objects.get(team=self.team, name="emoji-search-suggestions", version=version),
            created_by=self.user,
        )

    @parameterized.expand([("eu", "EU"), ("self_hosted", None)])
    def test_outside_us_cloud_it_returns_none(self, _name: str, region: str | None) -> None:
        self._publish_prompt(version=1, config={"model": NEW_MODEL})
        self._label_production(1)

        with override_settings(CLOUD_DEPLOYMENT=region):
            assert managed_decision_model.get_app_prompt("emoji-search-suggestions") is None

    def test_the_production_label_resolves(self) -> None:
        self._publish_prompt(version=1, config={"model": DEFAULT_DECISION_MODEL})
        self._publish_prompt(version=2, config={"model": NEW_MODEL})
        self._label_production(2)

        result = managed_decision_model.get_app_prompt("emoji-search-suggestions")

        assert result is not None
        assert result.config == {"model": NEW_MODEL}
        assert result.label == "production"
        assert result.source == "api"

    def test_an_exact_version_resolves_without_the_label(self) -> None:
        self._publish_prompt(version=1, config={"model": DEFAULT_DECISION_MODEL})
        self._publish_prompt(version=2, config={"model": NEW_MODEL})

        result = managed_decision_model.get_app_prompt("emoji-search-suggestions", version=1)

        assert result is not None
        assert result.config == {"model": DEFAULT_DECISION_MODEL}
        assert result.label is None

    def test_a_missing_prompt_returns_none(self) -> None:
        assert managed_decision_model.get_app_prompt("emoji-search-suggestions") is None

    def test_the_model_refresher_reads_the_database(self) -> None:
        self._publish_prompt(version=1, config={"model": NEW_MODEL})
        self._label_production(1)

        managed = ManagedDecisionModel("emoji-search-suggestions")
        managed._refresher._refresh()

        assert managed.current() == NEW_MODEL
        assert managed.fetch(version=1) == NEW_MODEL
