from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.llm.managed_decision_model import (
    DEFAULT_DECISION_MODEL,
    ManagedDecisionModel,
    get_app_prompt,
    model_from_config,
)

from products.ai_observability.backend.models.llm_prompt import LLMPrompt, LLMPromptLabel

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

    @patch("posthog.llm.managed_decision_model.posthoganalytics.api_key", "app-project-token")
    @patch("posthog.llm.managed_decision_model.get_prompt_by_name_from_cache")
    @patch("posthog.llm.managed_decision_model.Team.objects.get_team_from_token")
    def test_reads_app_project_prompt_without_personal_key(self, get_team, read_prompt) -> None:
        get_team.return_value = team = object()
        read_prompt.return_value = {"config": {"model": NEW_MODEL}}

        with patch("posthog.llm.managed_decision_model.posthoganalytics.personal_api_key", None):
            managed = ManagedDecisionModel("emoji-search-suggestions")
            managed._refresh()
            assert managed.fetch(version=3) == NEW_MODEL

        assert managed.current() == NEW_MODEL
        get_team.assert_called_with("app-project-token")
        read_prompt.assert_any_call(team, "emoji-search-suggestions", version=None, label="production")
        read_prompt.assert_any_call(team, "emoji-search-suggestions", version=3, label=None)

    @patch("posthog.llm.managed_decision_model.get_app_prompt")
    def test_missing_prompt_and_failed_refresh_keep_last_model(self, read_prompt) -> None:
        managed = ManagedDecisionModel("emoji-search-suggestions")
        read_prompt.return_value = {"config": {"model": NEW_MODEL}}
        managed._refresh()

        read_prompt.return_value = None
        managed._refresh()
        assert managed.current() == NEW_MODEL
        with self.assertRaisesRegex(RuntimeError, "version 3 was not found"):
            managed.fetch(version=3)

        read_prompt.side_effect = ConnectionError("unavailable")
        managed._refresh()
        assert managed.current() == NEW_MODEL

    @patch("posthog.llm.managed_decision_model.get_prompt_by_name_from_cache")
    @patch("posthog.llm.managed_decision_model.Team.objects.get_team_from_token")
    def test_missing_app_project_falls_back(self, get_team, read_prompt) -> None:
        get_team.return_value = None
        managed = ManagedDecisionModel("emoji-search-suggestions")

        managed._refresh()

        assert managed.current() == DEFAULT_DECISION_MODEL
        read_prompt.assert_not_called()
        assert get_app_prompt("emoji-search-suggestions") is None


class TestManagedPromptLookup(BaseTest):
    def test_reads_production_label_from_app_project(self) -> None:
        prompt = LLMPrompt.objects.create(
            team=self.team,
            name="emoji-search-suggestions",
            prompt="Emoji search",
            config={"model": NEW_MODEL},
        )
        LLMPromptLabel.objects.create(team=self.team, prompt_name=prompt.name, name="production", prompt=prompt)

        with (
            patch("posthog.llm.managed_decision_model.posthoganalytics.api_key", self.team.api_token),
            patch("posthog.llm.managed_decision_model.posthoganalytics.personal_api_key", None),
        ):
            assert ManagedDecisionModel(prompt.name).fetch() == NEW_MODEL
            assert ManagedDecisionModel(prompt.name).fetch(version=1) == NEW_MODEL
