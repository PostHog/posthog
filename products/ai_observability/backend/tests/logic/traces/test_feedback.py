from datetime import timedelta

from parameterized import parameterized

from products.ai_observability.backend.logic.traces.feedback import TraceFeedback, present_value

from .rows import T0, make_feedback_row

STEPS = [
    make_feedback_row(uuid="e0", event="$ai_span", span_id="span-a"),
    make_feedback_row(uuid="e1", event="$ai_generation", generation_id="gen-a", span_id="span-b"),
]


@parameterized.expand(
    [
        ("zero", "0", "0"),
        ("false", "false", "false"),
        ("a number", "4.5", "4.5"),
        ("a string", '"helpful"', "helpful"),
        ("a string that reads zero", '"0"', "0"),
        ("an object", '{"a": 1}', '{"a":1}'),
        ("a missing key", "", None),
        ("null", "null", None),
        ("an empty string", '""', None),
    ]
)
def test_present_value(_name: str, raw: str, expected: str | None) -> None:
    assert present_value(raw) == expected


def test_orders_entries_and_drops_empty_ones() -> None:
    rows = [
        make_feedback_row(
            uuid="m2", metric_name="resolved", metric_value_json="false", timestamp=T0 + timedelta(minutes=1)
        ),
        make_feedback_row(uuid="m1", metric_name="helpfulness", metric_value_json="0", timestamp=T0),
        make_feedback_row(uuid="m3", metric_name="tone", metric_value_json='""', timestamp=T0 + timedelta(minutes=2)),
        make_feedback_row(uuid="f1", event="$ai_feedback", feedback_text_json='""'),
    ]

    feedback = TraceFeedback("trace-1", rows)

    assert [(score.name, score.value) for score in feedback.scores] == [("helpfulness", "0"), ("resolved", "false")]
    assert feedback.texts == ()


@parameterized.expand(
    [
        ("the step's event uuid", "e1", "e1"),
        ("the step's generation id", "gen-a", "e1"),
        ("the trace id", "trace-1", "trace-1"),
        ("an id no step carries", "trace-event-span", "trace-1"),
        ("no parent", None, "trace-1"),
    ]
)
def test_entry_targets(_name: str, parent_id: str | None, node_id: str) -> None:
    feedback = TraceFeedback(
        "trace-1",
        [
            *STEPS,
            make_feedback_row(uuid="m1", parent_id=parent_id, metric_name="helpfulness", metric_value_json="4"),
            make_feedback_row(
                uuid="f1", event="$ai_feedback", parent_id=parent_id, feedback_text_json='"Too long, but correct."'
            ),
        ],
    )

    assert [score.node_id for score in feedback.scores] == [node_id]
    assert [(text.text, text.node_id) for text in feedback.texts] == [("Too long, but correct.", node_id)]
