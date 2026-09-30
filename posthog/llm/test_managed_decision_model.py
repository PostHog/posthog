from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.llm import managed_decision_model
from posthog.llm.managed_decision_model import (
    APP_PROMPT_CACHE,
    DEFAULT_DECISION_MODEL,
    ManagedDecisionModel,
    model_from_config,
)
from posthog.storage.llm_prompt_cache import invalidate_prompt_label_cache, invalidate_prompt_latest_cache
from posthog.storage.llm_prompt_cache_keys import prompt_label_cache_key
from posthog.utils import safe_cache_delete

from products.ai_observability.backend.models.llm_prompt import LLMPrompt, LLMPromptLabel

NEW_MODEL = "posthog/hogference/jeeves-0.1"


class TestAppPromptCache(SimpleTestCase):
    def setUp(self) -> None:
        APP_PROMPT_CACHE.clear()
        self.addCleanup(APP_PROMPT_CACHE.clear)

    @override_settings(CLOUD_DEPLOYMENT="US")
    @patch("posthog.storage.llm_prompt_cache.get_prompt_by_name_from_cache", return_value={"prompt": "p"})
    def test_each_prompt_and_version_is_read_once_per_refresh(self, read) -> None:
        for _ in range(2):
            managed_decision_model.get_app_prompt("a")
            managed_decision_model.get_app_prompt("a", version=1)
            managed_decision_model.get_app_prompt("b")

        assert read.call_count == 3


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
    PROMPT_NAME = "emoji-search-suggestions"

    def setUp(self) -> None:
        super().setUp()
        self.enterContext(override_settings(CLOUD_DEPLOYMENT="US"))
        self.enterContext(patch.object(managed_decision_model, "POSTHOG_PROMPTS_TEAM_ID", self.team.id))
        self._clear_caches()
        self.addCleanup(self._clear_caches)

    def _clear_caches(self) -> None:
        APP_PROMPT_CACHE.clear()
        invalidate_prompt_latest_cache(self.team.id, self.PROMPT_NAME)
        invalidate_prompt_label_cache(self.team.id, self.PROMPT_NAME, "production")
        safe_cache_delete(prompt_label_cache_key(self.team.id, self.PROMPT_NAME, "production"))

    def _publish_prompt(self, *, version: int, config: dict) -> None:
        LLMPrompt.objects.filter(team=self.team, name=self.PROMPT_NAME, is_latest=True).update(is_latest=False)
        LLMPrompt.objects.create(
            team=self.team,
            name=self.PROMPT_NAME,
            prompt="Suggest related emojis for a search.",
            version=version,
            is_latest=True,
            config=config,
            created_by=self.user,
        )

    def _label_production(self, version: int) -> None:
        LLMPromptLabel.objects.create(
            team=self.team,
            prompt_name=self.PROMPT_NAME,
            name="production",
            prompt=LLMPrompt.objects.get(team=self.team, name=self.PROMPT_NAME, version=version),
            created_by=self.user,
        )

    @parameterized.expand([("eu", "EU"), ("self_hosted", None)])
    def test_outside_us_cloud_it_returns_none(self, _name: str, region: str | None) -> None:
        self._publish_prompt(version=1, config={"model": NEW_MODEL})
        self._label_production(1)

        with override_settings(CLOUD_DEPLOYMENT=region):
            assert managed_decision_model.get_app_prompt(self.PROMPT_NAME) is None

    def test_the_production_label_resolves(self) -> None:
        self._publish_prompt(version=1, config={"model": DEFAULT_DECISION_MODEL})
        self._publish_prompt(version=2, config={"model": NEW_MODEL})
        self._label_production(2)

        result = managed_decision_model.get_app_prompt(self.PROMPT_NAME)

        assert result is not None
        assert result.config == {"model": NEW_MODEL}
        assert result.label == "production"
        assert result.source == "api"

    def test_an_exact_version_resolves_without_the_label(self) -> None:
        self._publish_prompt(version=1, config={"model": DEFAULT_DECISION_MODEL})
        self._publish_prompt(version=2, config={"model": NEW_MODEL})

        result = managed_decision_model.get_app_prompt(self.PROMPT_NAME, version=1)

        assert result is not None
        assert result.config == {"model": DEFAULT_DECISION_MODEL}
        assert result.label is None

    def test_a_missing_prompt_returns_none(self) -> None:
        assert managed_decision_model.get_app_prompt(self.PROMPT_NAME) is None

    def test_the_decision_model_reads_the_database(self) -> None:
        self._publish_prompt(version=1, config={"model": NEW_MODEL})
        self._label_production(1)

        managed = ManagedDecisionModel(self.PROMPT_NAME)

        assert managed.fetch() == NEW_MODEL
        assert managed.fetch(version=1) == NEW_MODEL
