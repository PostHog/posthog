from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from posthoganalytics.ai.prompts import PromptResult

from posthog.llm.managed_decision_model import DEFAULT_DECISION_MODEL, ManagedDecisionModel, model_from_config

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
        prompts.return_value.get.side_effect = ConnectionError("unavailable")
        managed._refresh()
        assert managed.current() == NEW_MODEL

    @patch("posthog.llm.managed_decision_model.posthoganalytics.personal_api_key", "")
    @patch("posthog.llm.managed_decision_model.Prompts")
    def test_without_a_key_uses_the_bundled_model(self, prompts) -> None:
        managed = ManagedDecisionModel("emoji-search-suggestions")

        managed._refresh()

        assert managed.current() == DEFAULT_DECISION_MODEL
        prompts.assert_not_called()
