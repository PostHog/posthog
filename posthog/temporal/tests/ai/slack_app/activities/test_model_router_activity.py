from collections.abc import Mapping

import pytest
from unittest.mock import MagicMock, patch

from posthog.llm.system_one import ChoiceAnswer, ChoiceQuestion, SystemOneResult
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.ai.slack_app.activities.model_router import route_slack_app_model_activity
from posthog.temporal.ai.slack_app.types import SlackAppModelOverride, SlackAppModelRouterInput

from products.slack_app.backend.models import SlackSettings
from products.slack_app.backend.services.model_router import PERSONAL_DEFAULT_NOTE
from products.tasks.backend.facade.ai_run_defaults import update_user_ai_run_preferences

MODULE = "posthog.temporal.ai.slack_app.activities.model_router"
SLACK_USER_ID = "U_ROUTER"


@pytest.fixture
def integration(db):
    organization = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=organization, name="Team")
    return Integration.objects.create(
        team=team,
        kind="slack",
        integration_id="T_ROUTER",
        sensitive_config={"access_token": "xoxb"},
    )


@pytest.fixture
def user(integration):
    return User.objects.create_and_join(integration.team.organization, "router@example.com", None)


def _input(
    integration: Integration, user: User, override: SlackAppModelOverride | None = None
) -> SlackAppModelRouterInput:
    return SlackAppModelRouterInput(
        integration_id=integration.id,
        slack_team_id=integration.integration_id or "",
        slack_user_id=SLACK_USER_ID,
        user_id=user.id,
        event_text="fix the flaky checkout test",
        thread_ts="1700000000.000100",
        repository="posthog/posthog",
        model_override=override,
    )


def _opt_in(integration: Integration) -> None:
    SlackSettings.objects.create(
        slack_workspace_id=integration.integration_id, slack_user_id=SLACK_USER_ID, auto_model_choice=True
    )


def _client_picking_personal_default() -> MagicMock:
    def decide(*, state: object, questions: Mapping[str, ChoiceQuestion]) -> SystemOneResult:
        criteria = questions["model"].criteria
        choice = next(key for key, description in criteria.items() if PERSONAL_DEFAULT_NOTE in str(description))
        return SystemOneResult(
            model="jev",
            answers={"model": ChoiceAnswer(choice=choice, confidence=0.9, probabilities={choice: 0.9})},
            input_tokens=None,
        )

    client = MagicMock()
    client.decide.side_effect = decide
    return client


class TestRouteSlackAppModelActivity:
    @pytest.mark.parametrize(
        "opted_in,flag_enabled,override",
        [
            # The author named a model, so the router has nothing to decide.
            (True, True, SlackAppModelOverride(model="gpt-6-sol", reasoning_effort=None)),
            (False, True, None),
            (True, False, None),
        ],
        ids=["model_named_in_mention", "not_opted_in", "flag_off"],
    )
    def test_ineligible_mention_keeps_its_override_without_asking_the_router(
        self, integration, user, opted_in, flag_enabled, override
    ):
        if opted_in:
            _opt_in(integration)
        with (
            patch(
                "products.slack_app.backend.feature_flags.posthoganalytics.feature_enabled", return_value=flag_enabled
            ),
            patch(f"{MODULE}.build_system_one_client") as build_client,
            patch(f"{MODULE}.capture_slack_event"),
        ):
            result = route_slack_app_model_activity(_input(integration, user, override))

        assert result == override
        build_client.assert_not_called()

    @pytest.mark.parametrize(
        "override,expected_effort",
        [
            (None, "high"),
            # An effort the author named still wins over the router's effort.
            (SlackAppModelOverride(model=None, reasoning_effort="low"), "low"),
        ],
        ids=["no_override", "effort_named_in_mention"],
    )
    def test_routed_mention_runs_on_the_picked_option(self, integration, user, override, expected_effort):
        _opt_in(integration)
        update_user_ai_run_preferences(
            integration.team_id, user.id, runtime_adapter="codex", model="gpt-6-sol", reasoning_effort="high"
        )
        with (
            patch("products.slack_app.backend.feature_flags.posthoganalytics.feature_enabled", return_value=True),
            patch(f"{MODULE}.build_system_one_client", return_value=_client_picking_personal_default()),
            patch(f"{MODULE}.capture_slack_event"),
        ):
            result = route_slack_app_model_activity(_input(integration, user, override))

        assert result == SlackAppModelOverride(model="gpt-6-sol", reasoning_effort=expected_effort)

    def test_router_failure_keeps_the_mention_on_its_default(self, integration, user):
        _opt_in(integration)
        client = MagicMock()
        client.decide.side_effect = TimeoutError()
        with (
            patch("products.slack_app.backend.feature_flags.posthoganalytics.feature_enabled", return_value=True),
            patch(f"{MODULE}.build_system_one_client", return_value=client),
            patch(f"{MODULE}.capture_slack_event"),
        ):
            result = route_slack_app_model_activity(_input(integration, user))

        assert result is None
