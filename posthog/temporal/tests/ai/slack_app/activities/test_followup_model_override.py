"""Tests for the model switch a follow-up can ask a run for.

The precedence rules themselves live in
``products/slack_app/backend/tests/services/test_run_preferences.py``. What is
covered here is what the follow-up path does with the answer: which asks reach the
agent server, which are refused in the thread, and what a resumed run is pinned to.
"""

from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.ai.slack_app.activities.task_creation import _apply_followup_model_override, _run_preference_state
from posthog.temporal.ai.slack_app.types import SlackAppModelOverride

from products.slack_app.backend.services.model_catalogue import ModelChoice
from products.slack_app.backend.services.slack_settings import AIPreferences

CATALOGUE = (
    ModelChoice("claude", "claude-sonnet-4-6", "Claude Sonnet 4.6", ("low", "medium", "high")),
    ModelChoice("claude", "claude-fable-5", "Claude Fable 5", ("low", "medium", "high", "xhigh", "max")),
    ModelChoice("codex", "gpt-5.6-sol", "GPT-5.6 Sol", ("low", "medium", "high", "xhigh", "max")),
)

RUNNING_STATE = {"runtime_adapter": "claude", "model": "claude-sonnet-4-6", "reasoning_effort": "medium"}


@pytest.fixture
def catalogue():
    with patch(
        "products.slack_app.backend.services.run_preferences.available_model_choices",
        return_value=CATALOGUE,
    ):
        yield


@pytest.fixture
def apply_config():
    with patch("products.tasks.backend.facade.api.apply_task_run_model_config", return_value=True) as mock:
        yield mock


def _run(state=None):
    return SimpleNamespace(id="run-1", team_id=7, state=state if state is not None else dict(RUNNING_STATE))


def _slack():
    return SimpleNamespace(client=MagicMock())


def _posted_text(slack) -> str:
    return slack.client.chat_postMessage.call_args.kwargs["text"]


class TestApplyFollowupModelOverride:
    @pytest.mark.parametrize("applied", [True, False], ids=["agent_server_accepts", "agent_server_refuses"])
    def test_switches_the_running_agent_without_announcing_it(self, catalogue, apply_config, applied):
        """The footer under the next reply reads the model back out of the run's state,
        so a switch that lands needs no line of its own, and one that doesn't must not
        claim otherwise."""
        apply_config.return_value = applied
        slack = _slack()
        _apply_followup_model_override(
            slack,
            "C1",
            "111.1",
            task_run=_run(),
            task_id="task-1",
            override=SlackAppModelOverride(model="claude-fable-5", reasoning_effort="xhigh"),
            actor_user=SimpleNamespace(id=42),
        )
        assert apply_config.call_args.kwargs == {
            "model": "claude-fable-5",
            "reasoning_effort": "xhigh",
            "actor_user_id": 42,
        }
        slack.client.chat_postMessage.assert_not_called()

    def test_refuses_a_model_from_the_other_runtime_without_touching_the_run(self, catalogue, apply_config):
        """The harness is the process the sandbox started with, so this one can only be
        answered — and it has to be, or the author is left thinking it was honoured."""
        slack = _slack()
        _apply_followup_model_override(
            slack,
            "C1",
            "111.1",
            task_run=_run(),
            task_id="task-1",
            override=SlackAppModelOverride(model="gpt-5.6-sol"),
            actor_user=SimpleNamespace(id=42),
        )
        apply_config.assert_not_called()
        assert "*GPT-5.6 Sol*" in _posted_text(slack)

    @pytest.mark.parametrize(
        "override",
        [
            None,
            SlackAppModelOverride(model="claude-sonnet-4-6", reasoning_effort="medium"),
        ],
        ids=["no_request", "already_on_it"],
    )
    def test_stays_quiet_when_nothing_changes(self, catalogue, apply_config, override):
        slack = _slack()
        _apply_followup_model_override(
            slack,
            "C1",
            "111.1",
            task_run=_run(),
            task_id="task-1",
            override=override,
            actor_user=SimpleNamespace(id=42),
        )
        apply_config.assert_not_called()
        slack.client.chat_postMessage.assert_not_called()


class TestRunPreferenceState:
    @pytest.mark.parametrize(
        "prefs,expected",
        [
            (
                AIPreferences(runtime_adapter="codex", model="gpt-5.6-sol", reasoning_effort="high"),
                {
                    "runtime_adapter": "codex",
                    "provider": "openai",
                    "model": "gpt-5.6-sol",
                    "reasoning_effort": "high",
                },
            ),
            # What was never resolved is left out rather than written as None, so the
            # agent server keeps its own default for it.
            (
                AIPreferences(runtime_adapter="claude", model="claude-fable-5", reasoning_effort=None),
                {"runtime_adapter": "claude", "provider": "anthropic", "model": "claude-fable-5"},
            ),
        ],
        ids=["full_triple", "no_effort_resolved"],
    )
    def test_pins_the_successor_run_to_what_resolved(self, prefs, expected):
        """A run created straight off a task writes these itself — without them the new
        sandbox falls back to whatever the agent server defaults to."""
        with patch(
            "products.slack_app.backend.facade.run_preferences.resolve_run_preferences",
            return_value=prefs,
        ):
            state = _run_preference_state(integration=None, slack_user_id="U1", model_override=None)
        assert state == expected
