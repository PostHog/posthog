from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from posthoganalytics.ai.prompts import PromptResult

from posthog.llm import managed_decision_model
from posthog.llm.managed_decision_model import (
    DEFAULT_DECISION_MODEL,
    ManagedDecisionModel,
    get_app_prompt,
    model_from_config,
)

NEW_MODEL = "posthog/hogference/jeeves-0.1"


def managed_result(model: str = NEW_MODEL) -> PromptResult:
    return PromptResult(
        source="api", prompt="Emoji search", name="emoji-search-suggestions", version=3, config={"model": model}
    )


class TestManagedDecisionModel(SimpleTestCase):
    def setUp(self) -> None:
        managed_decision_model.app_prompts.cache_clear()
        self.addCleanup(managed_decision_model.app_prompts.cache_clear)

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

    @patch("posthog.llm.managed_decision_model.posthoganalytics.personal_api_key", "phx_test")
    @patch("posthog.llm.managed_decision_model.Prompts")
    def test_every_refresh_reads_the_posthog_project_through_one_sdk_client(self, prompts_class) -> None:
        prompts_class.return_value.get.return_value = managed_result()
        managed = ManagedDecisionModel("emoji-search-suggestions")

        managed._refresh()
        managed._refresh()
        assert managed.fetch(version=3) == NEW_MODEL

        assert managed.current() == NEW_MODEL
        prompts_class.assert_called_once_with(managed_decision_model.posthoganalytics, capture_errors=True)
        get = prompts_class.return_value.get
        get.assert_any_call("emoji-search-suggestions", with_metadata=True, label="production", version=None)
        get.assert_any_call("emoji-search-suggestions", with_metadata=True, label=None, version=3)

    @patch("posthog.llm.managed_decision_model.get_app_prompt")
    def test_missing_prompt_and_failed_refresh_keep_last_model(self, read_prompt) -> None:
        managed = ManagedDecisionModel("emoji-search-suggestions")
        read_prompt.return_value = managed_result()
        managed._refresh()

        read_prompt.return_value = None
        managed._refresh()
        assert managed.current() == NEW_MODEL
        with self.assertRaisesRegex(RuntimeError, "version 3 was not found"):
            managed.fetch(version=3)

        read_prompt.side_effect = ConnectionError("unavailable")
        managed._refresh()
        assert managed.current() == NEW_MODEL

    @patch("posthog.llm.managed_decision_model.posthoganalytics.personal_api_key", None)
    @patch("posthog.llm.managed_decision_model.Prompts")
    def test_without_a_personal_key_the_bundled_model_stays(self, prompts_class) -> None:
        managed = ManagedDecisionModel("emoji-search-suggestions")

        managed._refresh()

        assert managed.current() == DEFAULT_DECISION_MODEL
        assert get_app_prompt("emoji-search-suggestions") is None
        prompts_class.assert_not_called()
