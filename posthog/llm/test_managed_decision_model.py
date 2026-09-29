from unittest.mock import patch

from django.test import SimpleTestCase

import posthoganalytics
from parameterized import parameterized
from posthoganalytics.ai.prompts import PromptResult, Prompts

from posthog.llm.managed_decision_model import (
    DEFAULT_DECISION_MODEL,
    PROMPT_CACHE_SECONDS,
    ManagedDecisionModel,
    model_from_config,
)

NEW_MODEL = "posthog/hogference/jeeves-0.1"


class TestManagedDecisionModel(SimpleTestCase):
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

    @patch("posthog.llm.managed_decision_model.posthoganalytics.personal_api_key", "test-key")
    @patch("posthog.llm.managed_decision_model.Prompts")
    def test_reads_production_label_and_keeps_previous_model_on_failure(self, prompts) -> None:
        managed = ManagedDecisionModel("emoji-search-suggestions")
        prompts.return_value.get.return_value = PromptResult(
            source="api", prompt="Emoji search", name="emoji-search-suggestions", version=2, config={"model": NEW_MODEL}
        )

        managed._refresh()

        assert managed.current() == NEW_MODEL
        assert prompts.return_value.get.call_args.kwargs["label"] == "production"
        managed.fetch(version=3)
        assert prompts.return_value.get.call_args.kwargs["version"] == 3
        assert prompts.return_value.get.call_args.kwargs["label"] is None
        assert "fallback" not in prompts.return_value.get.call_args.kwargs
        prompts.assert_called_once_with(
            posthoganalytics, capture_errors=True, default_cache_ttl_seconds=PROMPT_CACHE_SECONDS
        )
        prompts.return_value.get.side_effect = ConnectionError("unavailable")
        managed._refresh()
        assert managed.current() == NEW_MODEL

    @patch("posthog.llm.managed_decision_model.posthoganalytics.personal_api_key", "test-key")
    @patch("posthog.llm.managed_decision_model.Prompts")
    def test_sdk_code_fallback_does_not_replace_active_model(self, prompts) -> None:
        managed = ManagedDecisionModel("emoji-search-suggestions")
        prompts.return_value.get.return_value = PromptResult(
            source="api", prompt="Emoji search", config={"model": NEW_MODEL}
        )
        managed._refresh()

        prompts.return_value.get.return_value = PromptResult(source="code_fallback", prompt="Emoji search")
        managed._refresh()

        assert managed.current() == NEW_MODEL

    @patch("posthog.llm.managed_decision_model.posthoganalytics.personal_api_key", "test-key")
    @patch.object(Prompts, "_fetch_prompt_from_api")
    def test_reuses_sdk_cache_across_refreshes(self, fetch_prompt) -> None:
        fetch_prompt.return_value = {
            "name": "emoji-search-suggestions",
            "prompt": "Emoji search",
            "version": 2,
            "label": "production",
            "config": {"model": NEW_MODEL},
        }
        managed = ManagedDecisionModel("emoji-search-suggestions")

        managed._refresh()
        managed._refresh()

        assert managed.current() == NEW_MODEL
        fetch_prompt.assert_called_once_with("emoji-search-suggestions", None, "production")
        assert managed._prompts is not None
        assert managed._prompts._default_cache_ttl_seconds == PROMPT_CACHE_SECONDS

    @patch("posthog.llm.managed_decision_model.posthoganalytics.personal_api_key", "")
    @patch("posthog.llm.managed_decision_model.Prompts")
    def test_without_a_key_uses_the_bundled_model(self, prompts) -> None:
        managed = ManagedDecisionModel("emoji-search-suggestions")

        managed._refresh()

        assert managed.current() == DEFAULT_DECISION_MODEL
        prompts.assert_not_called()

        with self.assertRaisesRegex(RuntimeError, "POSTHOG_PERSONAL_API_KEY"):
            managed.fetch(version=3)
        prompts.assert_not_called()

    @patch("posthog.llm.managed_decision_model.Prompts")
    def test_initializes_sdk_only_after_key_is_available(self, prompts) -> None:
        managed = ManagedDecisionModel("emoji-search-suggestions")
        prompts.return_value.get.return_value = PromptResult(
            source="api", prompt="Emoji search", config={"model": NEW_MODEL}
        )
        with patch("posthog.llm.managed_decision_model.posthoganalytics.personal_api_key", ""):
            managed._refresh()
            prompts.assert_not_called()

        with patch("posthog.llm.managed_decision_model.posthoganalytics.personal_api_key", "test-key"):
            managed._refresh()

        assert managed.current() == NEW_MODEL
        prompts.assert_called_once()

    @patch("posthog.llm.managed_decision_model.Prompts")
    def test_losing_the_key_preserves_the_last_managed_model(self, prompts) -> None:
        managed = ManagedDecisionModel("emoji-search-suggestions")
        prompts.return_value.get.return_value = PromptResult(
            source="api", prompt="Emoji search", config={"model": NEW_MODEL}
        )

        with patch("posthog.llm.managed_decision_model.posthoganalytics.personal_api_key", "test-key"):
            managed._refresh()
        with patch("posthog.llm.managed_decision_model.posthoganalytics.personal_api_key", ""):
            managed._refresh()

        assert managed.current() == NEW_MODEL
        prompts.return_value.get.assert_called_once()
