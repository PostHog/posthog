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
from posthog.models.user import User
from posthog.temporal.ai.slack_app.activities.classifiers import classify_slack_app_model_override_activity
from posthog.temporal.ai.slack_app.types import SlackAppModelOverride, SlackAppModelOverrideInput

from products.slack_app.backend.services.model_catalogue import ModelChoice

CATALOGUE = (ModelChoice("claude", "claude-fable-5", "Claude Fable 5", ("low", "medium", "high")),)

ACTIVITY_MODULE = "posthog.temporal.ai.slack_app.activities.classifiers"


@pytest.fixture
def slack_user(db):
    organization = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=organization, name="Team")
    integration = Integration.objects.create(
        team=team,
        kind="slack",
        integration_id="T_WS",
        sensitive_config={"access_token": "xoxb"},
    )
    user = User.objects.create_and_join(organization, "someone@posthog.com", None)
    return integration, user


def _input(integration: Integration, user: User, text: str) -> SlackAppModelOverrideInput:
    return SlackAppModelOverrideInput(
        integration_id=integration.id,
        slack_team_id=integration.integration_id or "",
        user_id=user.id,
        event_text=text,
    )


class TestClassifySlackAppModelOverrideActivity:
    @pytest.mark.parametrize(
        "flag_on,catalogue",
        [
            (False, CATALOGUE),
            # The gateway is the source of truth for what can run; with no catalogue
            # there is nothing to validate a request against.
            (True, ()),
        ],
    )
    def test_gates_return_no_override_without_calling_the_llm(self, slack_user, flag_on, catalogue):
        integration, user = slack_user
        with (
            patch(f"{ACTIVITY_MODULE}.is_slack_app_model_classifier_enabled", return_value=flag_on),
            patch(f"{ACTIVITY_MODULE}.available_model_choices", return_value=catalogue),
            patch(f"{ACTIVITY_MODULE}.classify_slack_app_model_override") as classify,
        ):
            result = classify_slack_app_model_override_activity(_input(integration, user, "use fable for this one"))
        assert result is None
        classify.assert_not_called()

    def test_classifies_a_mention_that_names_no_model(self, slack_user):
        """No keyword gate stands in front of the classifier, so deciding that a
        mention carries no model instruction is the model's call."""
        integration, user = slack_user
        with (
            patch(f"{ACTIVITY_MODULE}.is_slack_app_model_classifier_enabled", return_value=True),
            patch(f"{ACTIVITY_MODULE}.available_model_choices", return_value=CATALOGUE),
            patch(f"{ACTIVITY_MODULE}.classify_slack_app_model_override", return_value=None) as classify,
        ):
            text = "fix the flaky checkout test"
            assert classify_slack_app_model_override_activity(_input(integration, user, text)) is None
        classify.assert_called_once_with(text, CATALOGUE)

    def test_returns_the_classified_override(self, slack_user):
        integration, user = slack_user
        override = SlackAppModelOverride(model="claude-fable-5", reasoning_effort="high")
        with (
            patch(f"{ACTIVITY_MODULE}.is_slack_app_model_classifier_enabled", return_value=True),
            patch(f"{ACTIVITY_MODULE}.available_model_choices", return_value=CATALOGUE),
            patch(f"{ACTIVITY_MODULE}.classify_slack_app_model_override", return_value=override),
        ):
            assert classify_slack_app_model_override_activity(_input(integration, user, "use fable")) == override
