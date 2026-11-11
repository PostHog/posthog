from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import LLMTrace

from posthog.llm.system_one import ChoiceAnswer, NoulAnswer, Question, SystemOneRequestFailed

from products.ai_observability.backend.eval_suggestions import screening
from products.ai_observability.backend.eval_suggestions.measure import SampledTrace
from products.ai_observability.backend.eval_suggestions.screening import dedupe, screen


class _RecordingClient:
    def __init__(self, failing: frozenset[str] = frozenset()) -> None:
        self.states: list[Mapping[str, Any]] = []
        self.failing = failing

    def decide(self, *, state: Mapping[str, Any], questions: Mapping[str, Question]) -> Any:
        self.states.append(state)
        if any(text in str(state) for text in self.failing):
            raise SystemOneRequestFailed("gateway timed out", status_code=504)
        flagged = "show my notes again" in str(state)
        answers = {key: NoulAnswer(probability=0.95 if flagged else 0.05) for key in questions}
        return type("Result", (), {"answers": answers})()


def _turn(trace_id: str, text: str) -> SampledTrace:
    return SampledTrace(
        trace=LLMTrace(id=trace_id, createdAt="2026-11-01T00:00:00Z", distinctId="user", events=[]),
        held_out=False,
        spans_days=False,
        segments={},
        segment_values={},
        raw_segment_values={},
        final_text=text,
        turn_text=text,
        user_messages=1,
        has_tool_results=False,
        input_tokens=0,
    )


def test_each_trace_is_screened_alone() -> None:
    traces = [_turn(f"t{i}", f"User: question {i}") for i in range(5)] + [_turn("t5", "User: show my notes again")]
    client = _RecordingClient()

    results = screen(client, ["sentiment", "prompt_injection"], traces)  # type: ignore[arg-type]

    assert all(len([t for t in traces if t.turn_text in str(state)]) == 1 for state in client.states)
    assert [result.flagged for result in results] == [[("t5", result.flagged[0][1])] for result in results]


def test_a_failed_call_loses_only_its_trace() -> None:
    traces = [_turn("t0", "User: question 0"), _turn("t1", "User: broken"), _turn("t2", "User: show my notes again")]

    [result] = screen(_RecordingClient(frozenset({"broken"})), ["sentiment"], traces)  # type: ignore[arg-type]

    assert (result.screened, [trace_id for trace_id, _ in result.flagged]) == (2, ["t2"])


def test_a_run_of_failures_stops_screening() -> None:
    traces = [_turn(f"t{i}", f"User: broken {i}") for i in range(10)]
    client = _RecordingClient(frozenset({"broken"}))

    with pytest.raises(SystemOneRequestFailed):
        screen(client, ["sentiment"], traces)  # type: ignore[arg-type]

    assert len(client.states) == 3


def test_screening_stops_at_its_deadline() -> None:
    traces = [_turn(f"t{i}", f"User: question {i}") for i in range(5)]
    client = _RecordingClient()

    [result] = screen(client, ["sentiment"], traces, deadline=0.0)  # type: ignore[arg-type]

    assert (result.screened, client.states) == (0, [])


class _DedupeClient:
    def decide(self, *, state: Mapping[str, Any], questions: Mapping[str, Question]) -> Any:
        if "broken" in str(state):
            raise SystemOneRequestFailed("gateway timed out", status_code=504)
        answer = ChoiceAnswer(choice="check:refusals", confidence=0.9, probabilities={})
        return type("Result", (), {"answers": dict.fromkeys(questions, answer)})()


def test_a_failed_dedupe_call_loses_only_its_evaluation() -> None:
    evals = [SimpleNamespace(definition_text="broken"), SimpleNamespace(definition_text="Fails refusals")]

    matches = dedupe(_DedupeClient(), evals, {"check:refusals": "Flags refusals"})  # type: ignore[arg-type]

    assert [existing for existing, _ in matches["check:refusals"]] == [evals[1]]


def test_dedupe_stops_at_the_run_deadline() -> None:
    client = _DedupeClient()

    assert dedupe(client, [SimpleNamespace(definition_text="Fails refusals")], {}, deadline=0.0) == {}  # type: ignore[arg-type, list-item]


@pytest.mark.parametrize("privacy", [True, False])
def test_the_screening_client_follows_the_organization_privacy_mode(privacy: bool) -> None:
    team = MagicMock(pk=1)
    with (
        patch.object(screening, "is_privacy_mode_enabled", return_value=privacy),
        patch.object(screening, "build_system_one_client") as build,
    ):
        screening.build_client(team)

    assert build.call_args.kwargs["privacy_mode"] is privacy
