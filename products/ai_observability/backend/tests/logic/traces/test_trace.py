from datetime import timedelta
from typing import Any

from parameterized import parameterized

from products.ai_observability.backend.logic.traces.trace import Trace
from products.ai_observability.backend.logic.traces.trace_queries import PersonRow

from .rows import T0, make_row


def trace(*rows: dict[str, Any], person: PersonRow | None = None) -> Trace:
    return Trace("trace-1", [make_row(**{"uuid": f"e{index}", **row}) for index, row in enumerate(rows)], person)


@parameterized.expand(
    [
        (
            "the root trace event reports the wall clock",
            [{"event": "$ai_trace", "latency": 9.0}, {"event": "$ai_generation", "latency": 2.0}],
            9.0,
        ),
        (
            "only generations report latency, so they are summed",
            [
                {"event": "$ai_generation", "latency": 1.25},
                {"event": "$ai_generation", "latency": 2.5, "parent_id": "span"},
                {"event": "$ai_span", "span_id": "span"},
            ],
            3.75,
        ),
        (
            "otherwise the direct children of the trace are summed",
            [
                {"event": "$ai_span", "span_id": "a", "latency": 4.0},
                {"event": "$ai_generation", "parent_id": "a", "latency": 3.0},
                {"event": "$ai_span", "latency": 1.0},
            ],
            5.0,
        ),
    ]
)
def test_total_latency(_name: str, rows: list[dict[str, Any]], expected: float) -> None:
    assert trace(*rows).totals.latency_s == expected


def test_totals_count_generations_and_embeddings_only_and_keep_unknown_cost_unknown() -> None:
    totals = trace(
        {"event": "$ai_generation", "input_tokens": 3, "cache_read_input_tokens": 2},
        {"event": "$ai_embedding", "input_tokens": 4},
        {"event": "$ai_span", "input_tokens": 100, "total_cost_usd": 5.0},
    ).totals

    assert (totals.input_tokens, totals.output_tokens, totals.cost_usd, totals.cache_read_tokens) == (7, None, None, 2)


def test_name_prefers_the_earliest_named_trace_event_over_other_events() -> None:
    named = trace(
        {"event": "$ai_span", "span_name": "early span", "timestamp": T0},
        {"event": "$ai_trace", "trace_name": "answer", "timestamp": T0 + timedelta(seconds=1), "parent_id": None},
    )

    assert named.name == "answer"
    assert trace({"event": "$ai_span", "span_name": "only span"}).name == "only span"
    assert trace({"event": "$ai_span"}).name is None
    assert trace({"event": "$ai_span"}).title == "Trace"


def test_errors_count_every_event_that_failed() -> None:
    failed = trace({"is_error": True}, {"error_is_truthy": True}, {})

    assert (failed.error_count, failed.has_error) == (2, True)


def test_thread_node_ids_hold_the_user_visible_generation() -> None:
    assert trace(
        {"uuid": "g1", "event": "$ai_generation", "timestamp": T0},
        {"uuid": "g2", "event": "$ai_generation", "timestamp": T0 + timedelta(seconds=1)},
    ).thread_node_ids == ["g2"]


@parameterized.expand(
    [
        ("email wins", PersonRow(distinct_id="u", email="ada@example.com", name="Ada"), "ada@example.com"),
        ("then name", PersonRow(distinct_id="u", email=None, name="Ada"), "Ada"),
        ("then distinct id", PersonRow(distinct_id="u", email=None, name=None), "u"),
        ("no person", None, None),
    ]
)
def test_person_label(_name: str, person: PersonRow | None, expected: str | None) -> None:
    assert trace({}, person=person).person_label == expected


@parameterized.expand(
    [
        (
            "a trace event makes the root the default",
            [{"event": "$ai_trace"}, {"event": "$ai_generation"}],
            "trace-1",
        ),
        (
            "otherwise the first top-level generation",
            [
                {"event": "$ai_span", "timestamp": T0},
                {"event": "$ai_generation", "timestamp": T0 + timedelta(seconds=1)},
                {"event": "$ai_generation", "timestamp": T0 + timedelta(seconds=2)},
            ],
            "e1",
        ),
        (
            "otherwise the first top-level node",
            [
                {"event": "$ai_span", "span_id": "s", "timestamp": T0},
                {"event": "$ai_generation", "parent_id": "s", "timestamp": T0 + timedelta(seconds=1)},
            ],
            "e0",
        ),
        ("a trace without nodes falls back to the root", [{"event": "$ai_feedback"}], "trace-1"),
    ]
)
def test_default_node_id(_name: str, rows: list[dict[str, Any]], expected: str) -> None:
    assert trace(*rows).default_node_id == expected


def test_node_ids_by_alias_map_sdk_ids_of_tree_nodes_to_their_uuids() -> None:
    aliases = trace(
        {"event": "$ai_span", "span_id": "span-a"},
        {"event": "$ai_generation", "generation_id": "gen-a", "parent_id": "span-a"},
        {"event": "$ai_generation", "generation_id": "gen-a"},
        {"event": "$ai_span", "span_id": "e3"},
        {"event": "$ai_feedback", "span_id": "feedback-a"},
        {"event": "$ai_trace", "span_id": "trace-a"},
    ).node_ids_by_alias

    assert aliases == {"span-a": "e0", "gen-a": "e1"}
