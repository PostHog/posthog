"""Gate tests for ``classify_slack_app_model_override_activity``.

The classifier's own prompt/parse behaviour is covered in
``posthog/temporal/tests/ai/test_classify_slack_app_model_override.py``. What
matters here is what guards it: the feature flag and an unreachable model
catalogue, each of which must produce "no override" without the LLM ever being
called.
"""

import pytest
from unittest.mock import patch

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.temporal.ai.slack_app.activities.classifiers import classify_slack_app_model_override_activity
from posthog.temporal.ai.slack_app.types import SlackAppModelOverride, SlackAppModelOverrideInput

from products.slack_app.backend.services.model_catalogue import ModelChoice

CATALOGUE = (ModelChoice("claude", "claude-fable-5", "Claude Fable 5", ("low", "medium", "high")),)

ACTIVITY_MODULE = "posthog.temporal.ai.slack_app.activities.classifiers"


@pytest.fixture
def integration(db):
    organization = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=organization, name="Team")
    return Integration.objects.create(
        team=team,
        kind="slack",
        integration_id="T_WS",
        sensitive_config={"access_token": "xoxb"},
    )


def _input(integration: Integration, text: str) -> SlackAppModelOverrideInput:
    return SlackAppModelOverrideInput(
        integration_id=integration.id,
        slack_team_id=integration.integration_id or "",
        event_text=text,
    )


class TestClassifySlackAppModelOverrideActivity:
    @pytest.mark.parametrize(
        "text,flag_on,catalogue",
        [
            ("use fable for this one", False, CATALOGUE),
            # The gateway is the source of truth for what can run; with no catalogue
            # there is nothing to validate a request against.
            ("use fable for this one", True, ()),
            # A follow-up that is only an attachment carries no sentence to read.
            ("   ", True, CATALOGUE),
        ],
        ids=["flag_off", "empty_catalogue", "blank_text"],
    )
    def test_gates_return_no_override_without_calling_the_llm(self, integration, text, flag_on, catalogue):
        with (
            patch(f"{ACTIVITY_MODULE}.is_slack_app_model_classifier_enabled", return_value=flag_on),
            patch(f"{ACTIVITY_MODULE}.available_model_choices", return_value=catalogue),
            patch(f"{ACTIVITY_MODULE}.classify_slack_app_model_override") as classify,
        ):
            result = classify_slack_app_model_override_activity(_input(integration, text))
        assert result is None
        classify.assert_not_called()

    @pytest.mark.parametrize(
        "classified",
        [
            # No keyword gate stands in front of the classifier, so deciding a mention
            # carries no model instruction is the model's call, not a word list's.
            None,
            SlackAppModelOverride(model="claude-fable-5", reasoning_effort="high"),
        ],
    )
    def test_passes_the_mention_to_the_classifier_and_returns_its_verdict(self, integration, classified):
        with (
            patch(f"{ACTIVITY_MODULE}.is_slack_app_model_classifier_enabled", return_value=True),
            patch(f"{ACTIVITY_MODULE}.available_model_choices", return_value=CATALOGUE),
            patch(f"{ACTIVITY_MODULE}.classify_slack_app_model_override", return_value=classified) as classify,
        ):
            text = "fix the flaky checkout test"
            assert classify_slack_app_model_override_activity(_input(integration, text)) == classified
        classify.assert_called_once_with(text, CATALOGUE)
