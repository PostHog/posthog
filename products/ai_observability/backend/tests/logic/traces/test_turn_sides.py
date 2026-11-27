import json

from unittest.mock import patch

from parameterized import parameterized

from products.ai_observability.backend.facade import contracts
from products.ai_observability.backend.logic.message_normalizer import run_limits
from products.ai_observability.backend.logic.message_normalizer.normalizer import RecipeNormalizer
from products.ai_observability.backend.logic.message_normalizer.pipeline import RunOutcome
from products.ai_observability.backend.logic.message_normalizer.values import MISSING, Value
from products.ai_observability.backend.logic.traces import previews
from products.ai_observability.backend.logic.traces.previews import PreviewSource, TracePreviewSources
from products.ai_observability.backend.logic.traces.turn import TIMED_OUT, Side, StepSide, shown, unread_reason
from products.ai_observability.backend.logic.traces.turn_sides import page_turn_sides

TEAM_ID = 7
NOTHING: StepSide = Side(value=None, unread=None)


def user(text: str) -> dict[str, str]:
    return {"role": "user", "content": text}


def assistant(text: str) -> dict[str, str]:
    return {"role": "assistant", "content": text}


def source(event_id: str, kind: contracts.TraceNodeKind, input: Value, output: Value) -> PreviewSource:
    return PreviewSource(
        event_id=event_id, kind=kind, input=Side(value=input, unread=None), output=Side(value=output, unread=None)
    )


def chat(question: str, answer: str) -> TracePreviewSources:
    both = source(f"g-{question}", "generation", [user(question)], [assistant(answer)])
    return TracePreviewSources(state=None, first_generation=both, latest_generation=both)


def texts(side: StepSide) -> list[str]:
    content = shown(side)
    assert isinstance(content, contracts.TraceMessagesSide)
    return [
        part.text for message in content.messages for part in message.parts if isinstance(part, contracts.TraceTextPart)
    ]


def node_ids(side: StepSide) -> set[str | None]:
    content = shown(side)
    assert isinstance(content, contracts.TraceMessagesSide)
    return {message.source_node_id for message in content.messages}


def page(sources: dict[str, TracePreviewSources], normalizer: type[RecipeNormalizer] = RecipeNormalizer):
    return page_turn_sides(sources, build_normalizer=normalizer, team_id=TEAM_ID)


@parameterized.expand(
    [
        ("a generation under its event id", "g1", "generation", "g1"),
        ("the trace's state under the trace id", "t1", "trace", "trace-1"),
    ]
)
def test_messages_carry_the_node_the_trace_view_opens(
    _name: str, event_id: str, kind: contracts.TraceNodeKind, node_id: str
) -> None:
    read = source(event_id, kind, [user("Where is my parcel?")], [assistant("On its way.")])
    sources = (
        TracePreviewSources(state=read, first_generation=None, latest_generation=None)
        if kind == "trace"
        else TracePreviewSources(state=None, first_generation=read, latest_generation=read)
    )

    sides = page({"trace-1": sources})["trace-1"]

    assert (node_ids(sides.input), node_ids(sides.output)) == ({node_id}, {node_id})


def test_a_generation_that_is_both_first_and_latest_is_read_once() -> None:
    with patch.object(previews, "read_step", wraps=previews.read_step) as read_step:
        sides = page({"trace-1": chat("Where is my parcel?", "On its way.")})["trace-1"]

    assert (read_step.call_count, texts(sides.input), texts(sides.output)) == (
        1,
        ["Where is my parcel?"],
        ["On its way."],
    )


def test_a_source_without_an_event_passes_on_why_it_was_not_read() -> None:
    not_read: Side[Value] = Side(value=None, unread=TIMED_OUT)
    unread = PreviewSource(event_id="", kind="generation", input=not_read, output=not_read)

    sides = page({"trace-1": TracePreviewSources(state=None, first_generation=unread, latest_generation=unread)})

    timed_out: StepSide = Side(value=None, unread=TIMED_OUT)
    assert (sides["trace-1"].input, sides["trace-1"].output) == (timed_out, timed_out)


def test_a_page_out_of_time_times_out_only_the_traces_it_did_not_read() -> None:
    with patch.object(run_limits, "time") as clock:
        clock.monotonic.return_value = 0.0

        class SpendingThePageOnTheFirstAnswer(RecipeNormalizer):
            def normalize_messages(self, value: Value, default_role: str, tools: Value = MISSING) -> RunOutcome:
                outcome = super().normalize_messages(value, default_role, tools)
                if "On its way." in json.dumps(value):
                    clock.monotonic.return_value = previews.PREVIEWS_TIME_LIMIT_SECONDS
                return outcome

        sides = page(
            {"first": chat("Where is my parcel?", "On its way."), "second": chat("Cancel my order", "Cancelled.")},
            SpendingThePageOnTheFirstAnswer,
        )

    timed_out: StepSide = Side(value=None, unread=TIMED_OUT)
    assert (texts(sides["first"].output), sides["second"].input, sides["second"].output) == (
        ["On its way."],
        timed_out,
        timed_out,
    )


@parameterized.expand(
    [
        ("no messages", Side(value=contracts.TraceMessagesSide(kind="messages", messages=[]), unread=None), True),
        ("a null value", Side(value=contracts.TraceJsonSide(kind="json", value=None), unread=None), True),
        ("a value", Side(value=contracts.TraceJsonSide(kind="json", value={"step": 1}), unread=None), False),
        ("nothing read", NOTHING, True),
    ]
)
def test_a_side_with_nothing_to_show_is_none(_name: str, side: StepSide, hidden: bool) -> None:
    assert (shown(side) is None) is hidden


def test_an_unread_side_says_why() -> None:
    assert (unread_reason(Side(value=None, unread=TIMED_OUT)), unread_reason(NOTHING)) == (
        contracts.TracePreviewMissingReason.TIMED_OUT,
        None,
    )
