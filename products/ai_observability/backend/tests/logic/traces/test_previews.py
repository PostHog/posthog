import json
from datetime import UTC, datetime, timedelta

from unittest.mock import patch

from parameterized import parameterized

from products.ai_observability.backend.logic.message_normalizer import run_limits
from products.ai_observability.backend.logic.message_normalizer.errors import RecipeRuntimeError
from products.ai_observability.backend.logic.message_normalizer.normalizer import RecipeNormalizer
from products.ai_observability.backend.logic.message_normalizer.pipeline import RunOutcome
from products.ai_observability.backend.logic.message_normalizer.values import MISSING, Value
from products.ai_observability.backend.logic.traces import previews
from products.ai_observability.backend.logic.traces.preview_queries import (
    PreviewEventRow,
    PreviewEventValues,
    StoredValue,
)
from products.ai_observability.backend.logic.traces.previews import (
    PreviewPicks,
    PreviewReads,
    PreviewSource,
    TracePreviewSources,
    page_turn_messages,
    page_turns,
    pick_preview_events,
    preview_sources,
)
from products.ai_observability.backend.logic.traces.turn import TIMED_OUT, TOO_LARGE, Side, Turn

T0 = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
TEAM_ID = 7


def row(uuid: str, event: str, minutes: int, *, has_state: bool = False, trace_id: str = "trace-1") -> PreviewEventRow:
    return PreviewEventRow(
        trace_id=trace_id, uuid=uuid, event=event, timestamp=T0 + timedelta(minutes=minutes), has_state=has_state
    )


def user(text: str) -> dict[str, str]:
    return {"role": "user", "content": text}


def assistant(text: str) -> dict[str, str]:
    return {"role": "assistant", "content": text}


def read(value: Value) -> Side[Value]:
    return Side(value=value, unread=None)


def generation(event_id: str, input: Value = None, output: Value = None) -> PreviewSource:
    return PreviewSource(event_id=event_id, kind="generation", input=read(input), output=read(output))


@parameterized.expand(
    [
        (
            "the earliest and the latest generation",
            [row("g1", "$ai_generation", 0), row("g2", "$ai_generation", 1), row("g3", "$ai_generation", 2)],
            PreviewPicks(state=None, first_generation="g1", latest_generation="g3"),
        ),
        (
            "the latest trace event that has state",
            [
                row("t1", "$ai_trace", 0, has_state=True),
                row("t2", "$ai_trace", 1, has_state=True),
                row("t3", "$ai_trace", 2),
            ],
            PreviewPicks(state="t2", first_generation=None, latest_generation=None),
        ),
        (
            "a tie in time picks the same generation for both ends",
            [row("g2", "$ai_generation", 0), row("g1", "$ai_generation", 0)],
            PreviewPicks(state=None, first_generation="g1", latest_generation="g1"),
        ),
    ]
)
def test_picks(_name: str, rows: list[PreviewEventRow], expected: PreviewPicks) -> None:
    assert pick_preview_events(rows) == {"trace-1": expected}


def test_a_trace_with_nothing_to_pick_has_no_entry() -> None:
    assert pick_preview_events([row("t1", "$ai_trace", 0)]) == {}


def test_reads_follow_each_events_role() -> None:
    picks = {"trace-1": PreviewPicks(state="s", first_generation="f", latest_generation="l")}

    assert PreviewReads.of(picks) == PreviewReads(
        trace_ids=("trace-1",), input_ids=("f", "s"), output_ids=("l", "s"), state_ids=("s",)
    )


def stored(value: Value, *, over_cap: bool = False, item_over_caps: tuple[bool, ...] | None = None) -> StoredValue:
    return StoredValue(value=value, over_cap=over_cap, item_over_caps=item_over_caps)


@parameterized.expand(
    [
        (
            "a tail keeps only what follows its last oversized item",
            "$ai_generation",
            {"$ai_input": stored([user("old"), None, user("new")], item_over_caps=(False, True, False))},
            Side(value=[user("new")], unread=TOO_LARGE),
        ),
        (
            "a tail whose last item is oversized keeps nothing",
            "$ai_generation",
            {"$ai_input": stored([user("old"), None], item_over_caps=(False, True))},
            Side(value=[], unread=TOO_LARGE),
        ),
        (
            "a null item that is not oversized stays in the tail",
            "$ai_generation",
            {"$ai_input": stored([user("hi"), None], item_over_caps=(False, False))},
            read([user("hi"), None]),
        ),
        (
            "a state that is not a tail is kept whole",
            "$ai_trace",
            {"$ai_input_state": stored([user("old"), None])},
            read([user("old"), None]),
        ),
        (
            "a state over the cap stands for its side as too large",
            "$ai_trace",
            {
                "$ai_input_state": stored(None, over_cap=True),
                "$ai_input": stored("plain question", item_over_caps=()),
            },
            Side(value=None, unread=TOO_LARGE),
        ),
        (
            "without state the trace event's input is read",
            "$ai_trace",
            {"$ai_input_state": stored(None), "$ai_input": stored("plain question", item_over_caps=())},
            read("plain question"),
        ),
    ]
)
def test_the_input_of_a_source(_name: str, event: str, values: dict[str, StoredValue], expected: Side[Value]) -> None:
    picks = {"trace-1": PreviewPicks(state="e", first_generation=None, latest_generation=None)}

    sources = preview_sources(picks, {"e": PreviewEventValues(uuid="e", event=event, values=values)})

    state = sources["trace-1"].state
    assert state is not None and state.input == expected


def test_a_page_takes_the_answer_from_state_and_the_message_from_the_first_generation() -> None:
    sources = {
        "with-state": TracePreviewSources(
            state=PreviewSource(
                event_id="t", kind="trace", input=read(None), output=read([assistant("From the state.")])
            ),
            first_generation=generation("g1", input=[user("First question")]),
            latest_generation=generation("g2", output=[assistant("Latest answer")]),
        ),
        "without-state": TracePreviewSources(
            state=None,
            first_generation=generation("g1", input=[user("First question")]),
            latest_generation=generation("g2", output=[assistant("Latest answer")]),
        ),
    }

    turns = page_turns(sources, build_normalizer=RecipeNormalizer, team_id=TEAM_ID)

    assert turns == {
        "with-state": Turn(message="First question", answer="From the state."),
        "without-state": Turn(message="First question", answer="Latest answer"),
    }


def test_a_page_of_messages_never_normalizes_an_output() -> None:
    normalized: list[Value] = []

    class Recording(RecipeNormalizer):
        def normalize_messages(self, value: Value, default_role: str, tools: Value = MISSING) -> RunOutcome:
            normalized.append(value)
            return super().normalize_messages(value, default_role, tools)

    sources = {
        "with-state": TracePreviewSources(
            state=PreviewSource(
                event_id="t", kind="trace", input=read("From the state?"), output=read([assistant("State answer")])
            ),
            first_generation=generation("g1", input=[user("Ignored")], output=[assistant("First answer")]),
            latest_generation=generation("g2", input=[user("Later")], output=[assistant("Latest answer")]),
        ),
        "one-generation": TracePreviewSources(
            state=None,
            first_generation=generation("g1", input=[user("Only question")], output=[assistant("Only answer")]),
            latest_generation=generation("g1", input=[user("Only question")], output=[assistant("Only answer")]),
        ),
    }

    messages = page_turn_messages(sources, build_normalizer=Recording, team_id=TEAM_ID)

    assert (messages, [value for value in normalized if "answer" in json.dumps(value)]) == (
        {"with-state": "From the state?", "one-generation": "Only question"},
        [],
    )
    assert [user("Later")] not in normalized


VIDEO_PART = {"type": "video_url", "video_url": {"url": "https://example.com/clip.mp4"}}


@parameterized.expand(
    [
        (
            "with text previews the text",
            [{"type": "text", "text": "Describe this clip"}, VIDEO_PART],
            "Describe this clip",
        ),
        ("alone previews nothing", [VIDEO_PART], None),
    ]
)
def test_a_video_part_is_never_the_message(_name: str, content: Value, expected: str | None) -> None:
    source = generation("g1", input=[{"role": "user", "content": content}])

    turns = page_turns(
        {"trace-1": TracePreviewSources(state=None, first_generation=source, latest_generation=source)},
        build_normalizer=RecipeNormalizer,
        team_id=TEAM_ID,
    )

    assert turns["trace-1"].message == expected


@parameterized.expand(
    [
        ("after the first trace is read", False, Turn(message="Where is my parcel?", answer="On its way.")),
        ("while the first trace's answer is read", True, Turn(message="Where is my parcel?", answer=TIMED_OUT)),
    ]
)
def test_a_page_out_of_time_times_out_what_it_did_not_read(_name: str, spend_first: bool, first: Turn) -> None:
    def chat(question: str, answer: str) -> TracePreviewSources:
        both = generation(f"g-{question}", input=[user(question)], output=[assistant(answer)])
        return TracePreviewSources(state=None, first_generation=both, latest_generation=both)

    with patch.object(run_limits, "time") as clock:
        clock.monotonic.return_value = 0.0

        class SpendingThePageOnTheFirstAnswer(RecipeNormalizer):
            def normalize_messages(self, value: Value, default_role: str, tools: Value = MISSING) -> RunOutcome:
                is_first_answer = "On its way." in json.dumps(value)
                if is_first_answer and spend_first:
                    clock.monotonic.return_value = previews.PREVIEWS_TIME_LIMIT_SECONDS
                outcome = super().normalize_messages(value, default_role, tools)
                if is_first_answer:
                    clock.monotonic.return_value = previews.PREVIEWS_TIME_LIMIT_SECONDS
                return outcome

        turns = page_turns(
            {"first": chat("Where is my parcel?", "On its way."), "second": chat("Cancel my order", "Cancelled.")},
            build_normalizer=SpendingThePageOnTheFirstAnswer,
            team_id=TEAM_ID,
        )

    assert turns == {"first": first, "second": Turn(message=TIMED_OUT, answer=TIMED_OUT)}


def test_the_normalizer_is_built_once_for_a_page_and_only_when_a_side_needs_it() -> None:
    builds: list[RecipeNormalizer] = []

    def build() -> RecipeNormalizer:
        builds.append(RecipeNormalizer())
        return builds[-1]

    def chat(question: str) -> TracePreviewSources:
        both = generation(f"g-{question}", input=[user(question)], output=[assistant("Done.")])
        return TracePreviewSources(state=None, first_generation=both, latest_generation=both)

    empty = generation("g-empty")
    page_turns(
        {"empty": TracePreviewSources(state=None, first_generation=empty, latest_generation=empty)},
        build_normalizer=build,
        team_id=TEAM_ID,
    )
    built_for_nothing = len(builds)
    page_turns({"first": chat("One"), "second": chat("Two")}, build_normalizer=build, team_id=TEAM_ID)

    assert (built_for_nothing, len(builds)) == (0, 1)


def test_a_side_that_fails_to_normalize_leaves_the_rest_of_the_page() -> None:
    class FailingOnCancel(RecipeNormalizer):
        def normalize_messages(self, value: Value, default_role: str, tools: Value = MISSING) -> RunOutcome:
            if "Cancel my order" in json.dumps(value):
                raise RecipeRuntimeError("The recipe failed on this input")
            return super().normalize_messages(value, default_role, tools)

    def chat(question: str, answer: str) -> TracePreviewSources:
        both = generation(f"g-{question}", input=[user(question)], output=[assistant(answer)])
        return TracePreviewSources(state=None, first_generation=both, latest_generation=both)

    turns = page_turns(
        {"broken": chat("Cancel my order", "Cancelled."), "intact": chat("Where is my parcel?", "On its way.")},
        build_normalizer=FailingOnCancel,
        team_id=TEAM_ID,
    )

    assert turns == {
        "broken": Turn(message=None, answer="Cancelled."),
        "intact": Turn(message="Where is my parcel?", answer="On its way."),
    }
