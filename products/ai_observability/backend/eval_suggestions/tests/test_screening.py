from collections.abc import Mapping
from typing import Any

import pytest

from posthog.schema import LLMTrace

from posthog.llm.system_one import NoulAnswer, Question, SystemOneRequestFailed

from products.ai_observability.backend.eval_suggestions.measure import SampledTrace
from products.ai_observability.backend.eval_suggestions.screening import screen


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
        raw_segments={},
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
