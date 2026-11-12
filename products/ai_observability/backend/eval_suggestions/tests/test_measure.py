import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.schema import LLMTrace, LLMTraceEvent

from posthog.models.ai_events.test_util import bulk_create_ai_events

from products.ai_observability.backend.eval_suggestions import measure, profile
from products.ai_observability.backend.eval_suggestions.adapters import _FINAL_TEXT, AdaptedCheck, compile_check
from products.ai_observability.backend.eval_suggestions.measure import (
    EVENTS_PER_TRACE,
    MAX_OUTPUT_BYTES,
    MAX_STATE_BYTES,
    ROLE_LABEL,
    SampledTrace,
    _calls_tools,
    _sampled_trace,
    fetch_sample,
    final_answer,
    run_check,
)
from products.ai_observability.backend.eval_suggestions.profile import ProfileWindow, fetch_profile


class TestSample(ClickhouseTestMixin, APIBaseTest):
    def _generation(
        self,
        trace_id: str,
        at: datetime,
        answer: str | None = "Here is the summary.",
        *,
        messages: list[dict[str, Any]] | None = None,
        properties: dict[str, Any] | None = None,
        copies: int = 1,
        output_state: str | None = None,
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
                        **(
                            {"$ai_output_choices": [{"role": "assistant", "content": answer}]}
                            if answer is not None
                            else {}
                        ),
                        **({"$ai_output_state": output_state} if output_state is not None else {}),
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

    def test_a_trace_with_a_long_graph_state_is_sampled_with_the_state_cut(self) -> None:
        end = timezone.now() - timedelta(minutes=30)
        self._generation("graph", end - timedelta(hours=3), output_state="s" * (MAX_STATE_BYTES * 2))
        window = ProfileWindow(start=end - timedelta(days=7), end=end)

        sample = fetch_sample(self.team, window, fetch_profile(self.team, window))

        [sampled] = sample.traces
        assert len(sampled.trace.events[0].properties["$ai_output_state"]) == MAX_STATE_BYTES

    def test_a_generation_answering_only_through_a_long_state_is_not_sampled(self) -> None:
        end = timezone.now() - timedelta(minutes=30)
        self._generation("short", end - timedelta(hours=4))
        self._generation("state_only", end - timedelta(hours=3), answer=None, output_state="s" * (MAX_STATE_BYTES + 1))
        window = ProfileWindow(start=end - timedelta(days=7), end=end)

        sample = fetch_sample(self.team, window, fetch_profile(self.team, window))

        assert [s.trace.id for s in sample.traces] == ["short"]

    def test_hydration_stops_once_the_sample_passes_its_byte_budget(self) -> None:
        end = timezone.now() - timedelta(minutes=30)
        for index in range(3):
            self._generation(f"trace-{index}", end - timedelta(hours=3, minutes=index))
        window = ProfileWindow(start=end - timedelta(days=7), end=end)

        with patch.object(measure, "MAX_SAMPLE_BYTES", 1), patch.object(measure, "HYDRATE_BATCH_TRACES", 1):
            sample = fetch_sample(self.team, window, fetch_profile(self.team, window))

        assert len(sample.traces) == 1

    def test_the_profile_counts_traffic_tools_errors_and_segments(self) -> None:
        end = timezone.now() - timedelta(minutes=30)
        for index, product in enumerate(["chat-1", "chat-2", "search"]):
            self._generation(
                f"trace-{index}",
                end - timedelta(hours=3, minutes=index),
                properties={"ai_product": product, "$ai_tools_called": "search, fetch", "$ai_session_id": "s1"},
            )
        self._generation(
            "failed",
            end - timedelta(days=2),
            properties={"ai_product": "search", "$ai_is_error": True, "$ai_error": "RateLimitError: slow down"},
        )
        window = ProfileWindow(start=end - timedelta(days=7), end=end)

        with patch.object(profile, "MIN_SEGMENT_GENERATIONS", 2):
            result = fetch_profile(self.team, window)

        assert (result.generations, result.traces, result.sessions) == (4, 4, 1)
        assert result.generations_by_days_ago == {0: 3, 2: 1}
        assert result.tool_counts == {"search": 3, "fetch": 3}
        assert result.tool_call_share == 0.75
        assert result.error_prefixes == ("RateLimitError: slow down",)
        assert result.segments == {"ai_product": {"chat": 2, "search": 2}}

    def test_hydration_reads_each_event_once_and_skips_traces_past_the_cap(self) -> None:
        end = timezone.now() - timedelta(minutes=30)
        # Ingestion can write one event twice. Counted twice, it would double tokens and use up the cap.
        self._generation("duplicated", end - timedelta(hours=5), copies=2)
        for index in range(EVENTS_PER_TRACE + 1):
            self._generation("too_long", end - timedelta(hours=4, seconds=index))
        window = ProfileWindow(start=end - timedelta(days=7), end=end)

        sample = fetch_sample(self.team, window, fetch_profile(self.team, window))

        assert [(s.trace.id, len(s.trace.events)) for s in sample.traces] == [("duplicated", 1)]

    @parameterized.expand(
        [
            ("text", "I archived all 40 notes."),
            # Longer than any byte cap on the raw message, so a cut in the JSON would lose the reply.
            ("long_text", "x" * 9000 + " I archived all 40 notes."),
            ("content_blocks", [{"type": "text", "text": "I archived all 40 notes."}]),
        ]
    )
    def test_a_trace_keeps_the_reply_the_user_answered(self, _name: str, content: Any) -> None:
        self._assert_previous_reply({"role": "assistant", "content": content})

    def test_a_trace_keeps_a_gemini_reply_the_user_answered(self) -> None:
        self._assert_previous_reply({"role": "model", "parts": [{"text": "I archived all 40 notes."}]})

    def test_a_trace_keeps_an_otel_reply_the_user_answered(self) -> None:
        self._assert_previous_reply(
            {"role": "assistant", "parts": [{"type": "text", "content": "I archived all 40 notes."}]}
        )

    def _assert_previous_reply(self, reply: dict[str, Any]) -> None:
        end = timezone.now() - timedelta(minutes=30)
        history = [
            {"role": "user", "content": "Archive my notes"},
            reply,
            {"role": "user", "content": "No, only the ones from March."},
        ]
        self._generation("turn", end - timedelta(hours=3), messages=history)
        window = ProfileWindow(start=end - timedelta(days=7), end=end)

        sampled = fetch_sample(self.team, window, fetch_profile(self.team, window)).traces[0]

        reply_at, correction = (
            sampled.turn_text.find("I archived all 40 notes."),
            sampled.turn_text.find("only the ones"),
        )
        assert 0 <= reply_at < correction
        assert len(sampled.turn_text) <= 3100


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


def test_boolean_segments_keep_the_spelling_filters_match() -> None:
    sampled = _sampled_trace(
        "t", [_row(0, {"is_paid": True})], held_out=False, spans_days=False, segment_keys=["is_paid"]
    )

    assert sampled is not None
    assert (sampled.segments, sampled.raw_segment_values) == ({"is_paid": "true"}, {"is_paid": frozenset({"true"})})
    assert sampled.raw_segment_values == {"is_paid": frozenset({"true"})}


def test_an_event_cut_to_fit_anywhere_in_the_trace_skips_it() -> None:
    rows = [_row(0, unreadable=True), _row(1, answer="Short final answer.")]
    assert _sampled_trace("t", rows, held_out=False, spans_days=False, segment_keys=[]) is None


@parameterized.expand(
    [
        # orjson refuses past 1024 levels, so the output stays a raw string.
        ("raw_output", 9, "[" * 2000 + "]" * 2000),
        ("parsed_output", 9, "[" * 600 + "]" * 600),
        ("parsed_output_state", 14, "[" * 600 + "]" * 600),
    ]
)
def test_a_trace_nested_too_deep_to_read_is_skipped(_name: str, column: int, value: str) -> None:
    deep = list(_row(1))
    deep[column] = value
    rows = [_row(0, answer="Short final answer."), tuple(deep)]
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
        final_text="",
        turn_text="",
        user_messages=1,
        has_tool_results=False,
        input_tokens=0,
    )

    [outcome] = run_check(compile_check(check), [sampled])

    assert outcome.failed is failed


def test_a_check_stops_at_the_deadline() -> None:
    sampled = SampledTrace(
        trace=LLMTrace(id="t", createdAt=AT.isoformat(), distinctId="u", events=[]),
        held_out=False,
        spans_days=False,
        segments={},
        segment_values={},
        raw_segment_values={},
        final_text="",
        turn_text="",
        user_messages=1,
        has_tool_results=False,
        input_tokens=0,
    )
    check = AdaptedCheck(key="k", name="n", description="d", source="return true", template_key="", severity=1.0)

    assert run_check(compile_check(check), [sampled], deadline=time.monotonic() - 1) == []


@parameterized.expand(
    [
        ("empty_tool_calls", [{"role": "assistant", "content": "Done.", "tool_calls": []}], False),
        ("null_tool_calls", [{"role": "assistant", "content": "Done.", "tool_calls": None}], False),
        ("function_call", [{"role": "assistant", "tool_calls": [{"function": {"name": "search"}}]}], True),
        ("otel_part", [{"role": "assistant", "parts": [{"type": "tool_call", "name": "search"}]}], True),
        ("schema_type_list", [{"role": "assistant", "content": "{}", "schema": {"type": ["string", "null"]}}], False),
    ]
)
def test_only_a_populated_tool_call_makes_a_generation_a_step(_name: str, output: list, expected: bool) -> None:
    event = LLMTraceEvent(
        id="e", event="$ai_generation", createdAt=AT.isoformat(), properties={"$ai_output_choices": output}
    )
    assert _calls_tools(event) is expected


def test_a_tool_call_held_in_the_output_state_makes_a_generation_a_step() -> None:
    state = [{"role": "assistant", "tool_calls": [{"function": {"name": "search"}}]}]
    event = LLMTraceEvent(
        id="e", event="$ai_generation", createdAt=AT.isoformat(), properties={"$ai_output_state": state}
    )
    assert _calls_tools(event) is True


def _generation_event(index: int, output: Any) -> LLMTraceEvent:
    return LLMTraceEvent(
        id=f"e{index}",
        event="$ai_generation",
        createdAt=(AT + timedelta(seconds=index)).isoformat(),
        properties={"$ai_output_choices": output},
    )


def _text(content: str) -> list[dict[str, Any]]:
    return [{"role": "assistant", "content": content}]


_SEARCH_CALL = {"type": "function", "id": "c1", "function": {"name": "search", "arguments": "{}"}}


# Python picks the answer for screening and gap search, and Hog picks it inside the checks, so both read these cases.
@parameterized.expand(
    [
        ("plain_answer", [_text("All done.")], "All done."),
        (
            "tool_call_then_answer",
            [[{"role": "assistant", "content": "", "tool_calls": [_SEARCH_CALL]}], _text("Found it.")],
            "Found it.",
        ),
        (
            "answer_then_tool_call",
            [_text("Found it."), [{"role": "assistant", "content": "", "tool_calls": [_SEARCH_CALL]}]],
            "Found it.",
        ),
        ("empty_tool_calls_list", [[{"role": "assistant", "content": "Found it.", "tool_calls": []}]], "Found it."),
        (
            "anthropic_tool_use_block",
            [
                _text("Found it."),
                [
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "Searching"},
                            {"type": "tool_use", "id": "c2", "name": "search", "input": {}},
                        ],
                    }
                ],
            ],
            "Found it.",
        ),
        (
            "otel_tool_call_part",
            [
                _text("Found it."),
                [
                    {
                        "role": "assistant",
                        "parts": [{"type": "tool_call", "name": "search", "arguments": {}, "id": "c3"}],
                    }
                ],
            ],
            "Found it.",
        ),
        ("no_text", [[{"role": "assistant", "content": ""}]], ""),
    ]
)
def test_python_and_hog_pick_the_same_final_answer(_name: str, outputs: list[Any], expected: str) -> None:
    events = [_generation_event(index, output) for index, output in enumerate(outputs)]
    check = AdaptedCheck(
        key="k",
        name="n",
        description="d",
        source=_FINAL_TEXT + "\nprint(final_text)\nreturn true",
        template_key="",
        severity=1.0,
    )
    [outcome] = run_check(
        compile_check(check),
        [
            SampledTrace(
                trace=LLMTrace(id="t", createdAt=AT.isoformat(), distinctId="u", events=events),
                held_out=False,
                spans_days=False,
                segments={},
                segment_values={},
                raw_segment_values={},
                final_text="",
                turn_text="",
                user_messages=1,
                has_tool_results=False,
                input_tokens=0,
            )
        ],
    )

    hog_answer = ROLE_LABEL.sub("", outcome.reasoning.strip()) if outcome.failed is False else ""
    assert (final_answer(events), hog_answer) == (expected, expected)
