from collections.abc import Mapping
from dataclasses import dataclass

import pytest
from unittest.mock import MagicMock, patch

from posthog.llm.system_one import ChoiceAnswer, ChoiceQuestion, SystemOneResult
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.ai.slack_app.activities.model_router import classify_slack_app_model_router_activity
from posthog.temporal.ai.slack_app.types import SlackAppModelOverride, SlackAppModelRouterInput

from products.slack_app.backend.models import SlackSettings
from products.slack_app.backend.services.model_catalogue import ModelChoice
from products.slack_app.backend.services.model_router import PERSONAL_DEFAULT_NOTE
from products.tasks.backend.facade.ai_run_defaults import update_user_ai_run_preferences

MODULE = "posthog.temporal.ai.slack_app.activities.model_router"
OPTIONS_MODULE = "products.slack_app.backend.services.model_router"
FLAG = "products.slack_app.backend.feature_flags.posthoganalytics.feature_enabled"
SLACK_USER_ID = "U_ROUTER"

_EFFORTS = ("low", "medium", "high", "xhigh", "max")
# A fixed catalogue and ladder, so the snapshot moves when the router's own text changes
# and not each time the catalog prices or ships a model.
CHOICES = (
    ModelChoice("claude", "claude-sonnet-5-5", "Claude Sonnet 5.5", _EFFORTS, "1×"),
    ModelChoice("claude", "claude-opus-5-5", "Claude Opus 5.5", _EFFORTS, "2×"),
    ModelChoice("codex", "gpt-6-luna", "GPT-6 Luna", _EFFORTS, "0.05×"),
    ModelChoice("codex", "gpt-6-sol", "GPT-6 Sol", _EFFORTS, "1×"),
)


@dataclass(frozen=True)
class _Notch:
    model: str
    effort: str


LADDER = {
    "claude": (_Notch("claude-sonnet-5-5", "medium"), _Notch("claude-opus-5-5", "xhigh")),
    "codex": (_Notch("gpt-6-luna", "low"), _Notch("gpt-6-sol", "high")),
}


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


def _client_picking(model: str | None = None) -> MagicMock:
    def decide(*, state: object, questions: Mapping[str, ChoiceQuestion]) -> SystemOneResult:
        criteria = questions["model"].criteria
        choice = model or next(
            key for key, description in criteria.items() if PERSONAL_DEFAULT_NOTE in str(description)
        )
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
            patch(FLAG, return_value=flag_enabled),
            patch(f"{MODULE}.build_system_one_client") as build_client,
            patch(f"{MODULE}.capture_slack_event"),
        ):
            result = classify_slack_app_model_router_activity(_input(integration, user, override))

        assert result == override
        build_client.assert_not_called()

    @pytest.mark.parametrize(
        "picked,override,expected",
        [
            (None, None, SlackAppModelOverride(model="gpt-6-sol", reasoning_effort="high")),
            (
                None,
                SlackAppModelOverride(model=None, reasoning_effort="low"),
                SlackAppModelOverride(model="gpt-6-sol", reasoning_effort="low"),
            ),
            ("claude-opus-5-5", None, SlackAppModelOverride(model="claude-opus-5-5", reasoning_effort=None)),
        ],
        ids=["picks_personal_default", "effort_named_in_mention", "picks_ladder_model"],
    )
    def test_routed_mention_runs_on_the_picked_model(self, integration, user, picked, override, expected):
        _opt_in(integration)
        update_user_ai_run_preferences(
            integration.team_id, user.id, runtime_adapter="codex", model="gpt-6-sol", reasoning_effort="high"
        )
        with (
            patch(FLAG, return_value=True),
            patch(f"{MODULE}.build_system_one_client", return_value=_client_picking(picked)),
            patch(f"{MODULE}.capture_slack_event"),
        ):
            result = classify_slack_app_model_router_activity(_input(integration, user, override))

        assert result == expected

    def test_router_failure_keeps_the_mention_on_its_default(self, integration, user):
        _opt_in(integration)
        client = MagicMock()
        client.decide.side_effect = TimeoutError()
        with (
            patch(FLAG, return_value=True),
            patch(f"{MODULE}.build_system_one_client", return_value=client),
            patch(f"{MODULE}.capture_slack_event"),
        ):
            result = classify_slack_app_model_router_activity(_input(integration, user))

        assert result is None

    def test_request_to_the_decision_model_matches_snapshot(self, integration, user, snapshot):
        _opt_in(integration)
        update_user_ai_run_preferences(
            integration.team_id, user.id, runtime_adapter="codex", model="gpt-6-sol", reasoning_effort="high"
        )
        client = _client_picking()
        with (
            patch(FLAG, return_value=True),
            patch("products.tasks.backend.facade.run_config.get_model_access_error", return_value=None),
            patch(f"{OPTIONS_MODULE}.available_model_choices", return_value=CHOICES),
            patch(f"{OPTIONS_MODULE}.offered_model_choices", return_value=CHOICES),
            patch(f"{OPTIONS_MODULE}.CAPABILITY_LADDER_BY_RUNTIME_ADAPTER", LADDER),
            patch(f"{MODULE}.build_system_one_client", return_value=client),
            patch(f"{MODULE}.capture_slack_event"),
        ):
            classify_slack_app_model_router_activity(_input(integration, user))

        request = client.decide.call_args.kwargs
        assert {"state": request["state"], "question": request["questions"]["model"].to_json()} == snapshot
