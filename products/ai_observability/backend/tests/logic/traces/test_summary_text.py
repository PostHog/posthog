from typing import Any

from products.ai_observability.backend.logic.traces.summary_text import render_trace
from products.ai_observability.backend.logic.traces.trace import Trace
from products.ai_observability.backend.logic.traces.trace_queries import TraceNodeRow

from .rows import T0, make_row

SPAN = "span-uuid"
GENERATION = "gen-uuid"
TRACE_EVENT = "trace-event-uuid"
QUESTION = "Which plan includes priority support?"


def _contents(uuid: str, event: str, properties: dict[str, Any]) -> TraceNodeRow:
    return TraceNodeRow(uuid=uuid, event=event, timestamp=T0, properties=properties)


def _owners_of(text: str, owners: tuple[str | None, ...], needle: str) -> set[str | None]:
    return {owner for line, owner in zip(text.split("\n"), owners) if needle in line}


def test_each_step_owns_its_rendered_lines() -> None:
    trace = Trace(
        "trace-1",
        [
            make_row(uuid=SPAN, span_id="span-1", span_name="router"),
            make_row(uuid=GENERATION, event="$ai_generation", parent_id="span-1", model="gpt-4.1-mini"),
        ],
        None,
    )
    steps = [
        _contents(SPAN, "$ai_span", {"$ai_span_name": "router"}),
        _contents(GENERATION, "$ai_generation", {"$ai_input": [{"role": "user", "content": QUESTION}]}),
    ]

    rendered = render_trace(trace, None, steps, budget=100_000)

    assert _owners_of(rendered.text, rendered.line_owners, QUESTION) == {GENERATION}
    assert _owners_of(rendered.text, rendered.line_owners, "router") == {SPAN}
    assert rendered.line_owners[0] is None


def test_a_trace_without_steps_renders_its_state() -> None:
    trace = Trace("trace-1", [make_row(uuid=TRACE_EVENT, event="$ai_trace", span_name="lookup")], None)
    trace_event = _contents(
        TRACE_EVENT,
        "$ai_trace",
        {"$ai_input_state": {"order": "A-1042"}, "$ai_output_state": {"status": "shipped"}},
    )

    rendered = render_trace(trace, trace_event, [], budget=100_000)

    assert "A-1042" in rendered.text and "shipped" in rendered.text
    assert set(rendered.line_owners) == {None}


def test_the_budget_samples_the_text() -> None:
    generations = [make_row(uuid=f"gen-{index}", event="$ai_generation") for index in range(100)]
    steps = [
        _contents(f"gen-{index}", "$ai_generation", {"$ai_input": [{"role": "user", "content": QUESTION}]})
        for index in range(100)
    ]

    rendered = render_trace(Trace("trace-1", generations, None), None, steps, budget=2_000)

    assert rendered.was_sampled and len(rendered.text) <= 2_000
