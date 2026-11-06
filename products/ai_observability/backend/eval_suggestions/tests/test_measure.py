import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event

from django.utils import timezone

from parameterized import parameterized

from posthog.schema import LLMTrace

from posthog.models.ai_events.test_util import bulk_create_ai_events

from products.ai_observability.backend.eval_suggestions.adapters import AdaptedCheck, compile_check
from products.ai_observability.backend.eval_suggestions.measure import (
    EVENTS_PER_TRACE,
    MAX_OUTPUT_BYTES,
    SampledTrace,
    _sampled_trace,
    fetch_sample,
    run_check,
)
from products.ai_observability.backend.eval_suggestions.profile import ProfileWindow, fetch_profile


class TestSample(ClickhouseTestMixin, APIBaseTest):
    def _generation(
        self,
        trace_id: str,
        at: datetime,
        answer: str = "Here is the summary.",
        *,
        messages: list[dict[str, str]] | None = None,
        properties: dict[str, str] | None = None,
        copies: int = 1,
    ) -> None:
        event_uuid = str(uuid.uuid4())
        light = {"$ai_trace_id": trace_id, "$ai_model": "example-model-mini", **(properties or {})}
        _create_event(
            team=self.team,
            event="$ai_generation",
            distinct_id="user-1",
            timestamp=at,
            properties=light,
            event_uuid=event_uuid,
        )
        bulk_create_ai_events(
            [
                {
                    "event": "$ai_generation",
                    "event_uuid": event_uuid,
                    "distinct_id": "user-1",
                    "team_id": self.team.pk,
                    "timestamp": at,
                    "properties": {
                        **light,
                        "$ai_input": messages or [{"role": "user", "content": "Summarize my notes"}],
                        "$ai_output_choices": [{"role": "assistant", "content": answer}],
                    },
                }
            ]
            * copies
        )

    def test_a_trace_across_the_held_out_boundary_is_sampled_once(self) -> None:
        end = timezone.now() - timedelta(minutes=30)
        self._generation("older", end - timedelta(days=3))
        self._generation("across", end - timedelta(days=1, hours=1))
        self._generation("across", end - timedelta(hours=2))
        self._generation("recent", end - timedelta(hours=3))
        window = ProfileWindow(start=end - timedelta(days=7), end=end)

        sample = fetch_sample(self.team, window, fetch_profile(self.team, window))

        assert sorted(s.trace.id for s in sample.main) == ["across", "older"]
        assert [s.trace.id for s in sample.held_out] == ["recent"]

    def test_a_trace_whose_final_answer_is_too_long_to_read_is_not_sampled(self) -> None:
        end = timezone.now() - timedelta(minutes=30)
        self._generation("short", end - timedelta(hours=5))
        self._generation("long", end - timedelta(hours=4))
        self._generation("long", end - timedelta(hours=3), answer="x" * (MAX_OUTPUT_BYTES + 1))
        window = ProfileWindow(start=end - timedelta(days=7), end=end)

        sample = fetch_sample(self.team, window, fetch_profile(self.team, window))

        assert [s.trace.id for s in sample.traces] == ["short"]

    def test_hydration_reads_each_event_once_and_skips_traces_past_the_cap(self) -> None:
        end = timezone.now() - timedelta(minutes=30)
        # Ingestion can write one event twice. Counted twice, it would double tokens and use up the cap.
        self._generation("duplicated", end - timedelta(hours=5), copies=2)
        for index in range(EVENTS_PER_TRACE + 1):
            self._generation("too_long", end - timedelta(hours=4, seconds=index))
        window = ProfileWindow(start=end - timedelta(days=7), end=end)

        sample = fetch_sample(self.team, window, fetch_profile(self.team, window))

        assert [(s.trace.id, len(s.trace.events)) for s in sample.traces] == [("duplicated", 1)]

    def test_a_trace_keeps_the_reply_the_user_answered(self) -> None:
        end = timezone.now() - timedelta(minutes=30)
        history = [
            {"role": "user", "content": "Archive my notes"},
            {"role": "assistant", "content": "I archived all 40 notes."},
            {"role": "user", "content": "No, only the ones from March."},
        ]
        self._generation("turn", end - timedelta(hours=3), messages=history)
        window = ProfileWindow(start=end - timedelta(days=7), end=end)

        sampled = fetch_sample(self.team, window, fetch_profile(self.team, window)).traces[0]

        reply, correction = sampled.turn_text.find("I archived all 40 notes."), sampled.turn_text.find("only the ones")
        assert 0 <= reply < correction


AT = datetime(2026, 11, 1, tzinfo=UTC)


def _row(
    index: int,
    properties: dict[str, Any] | None = None,
    *,
    answer: str = "",
    unreadable: bool = False,
    previous: str = "",
) -> tuple[Any, ...]:
    """One hydration row, in the column order of _HYDRATE_SQL."""
    output = json.dumps([{"role": "assistant", "content": answer}]) if answer else ""
    return (
        "t",
        f"e{index}",
        "$ai_generation",
        AT + timedelta(seconds=index),
        "u",
        properties or {},
        "",
        1,
        False,
        output,
        "",
        unreadable,
        previous,
        "",
        "",
    )


def test_a_trace_holds_the_segment_value_of_every_generation() -> None:
    rows = [_row(index, {"ai_product": product}) for index, product in enumerate(["chat-1", "search"])]

    sampled = _sampled_trace("t", rows, held_out=False, spans_days=False, segment_keys=["ai_product"])

    assert sampled is not None
    assert sampled.segments == {"ai_product": "search"}
    assert sampled.segment_values == {"ai_product": frozenset({"chat", "search"})}
    assert sampled.raw_segment_values == {"ai_product": frozenset({"chat-1", "search"})}


def test_a_long_earlier_reply_leaves_room_for_the_current_turn() -> None:
    history = json.dumps({"role": "assistant", "content": "x" * 5000})

    sampled = _sampled_trace("t", [_row(0, previous=history)], held_out=False, spans_days=False, segment_keys=[])

    assert sampled is not None
    assert len(sampled.turn_text) <= 3100
    assert sampled.turn_text.index("User:") < 3000


def test_an_event_cut_to_fit_anywhere_in_the_trace_skips_it() -> None:
    rows = [_row(0, unreadable=True), _row(1, answer="Short final answer.")]
    assert _sampled_trace("t", rows, held_out=False, spans_days=False, segment_keys=[]) is None


@parameterized.expand(
    [
        ("plain_answer", {}, 0.0),
        ("malformed_token_count", {"$ai_input_tokens": "lots"}, 0.0),
        ("numeric_token_count", {"$ai_input_tokens": "120"}, 120.0),
    ]
)
def test_a_trace_survives_malformed_metadata(_name: str, properties: dict[str, Any], tokens: float) -> None:
    sampled = _sampled_trace(
        "t", [_row(0, properties, answer="Done.")], held_out=False, spans_days=False, segment_keys=[]
    )
    assert sampled is not None and sampled.input_tokens == tokens


def test_the_final_text_drops_the_renderers_role_label() -> None:
    answer = json.dumps([{"role": "assistant", "parts": [{"type": "text", "content": '{"status": "done"}'}]}])
    row = list(_row(0))
    row[9] = answer

    sampled = _sampled_trace("t", [tuple(row)], held_out=False, spans_days=False, segment_keys=[])

    assert sampled is not None and not sampled.final_text.lower().startswith("assistant:")


@parameterized.expand(
    [
        ("pass", "return true", False),
        ("fail", "return false", True),
        ("not_applicable", "return null", None),
        ("runtime_error", "return 1 / 0", None),
    ]
)
def test_run_check_maps_each_verdict(_name: str, source: str, failed: bool | None) -> None:
    check = AdaptedCheck(key="k", name="n", description="d", source=source, template_key="", severity=1.0)
    trace = LLMTrace(id="t", createdAt="2026-11-01T00:00:00Z", distinctId="u", events=[])
    sampled = SampledTrace(
        trace=trace,
        held_out=False,
        spans_days=False,
        segments={},
        segment_values={},
        raw_segment_values={},
        raw_segments={},
        final_text="",
        turn_text="",
        user_messages=1,
        has_tool_results=False,
        input_tokens=0,
    )

    [outcome] = run_check(compile_check(check), [sampled])

    assert outcome.failed is failed
