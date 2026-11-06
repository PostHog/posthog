from datetime import timedelta
from typing import Any

from products.ai_observability.backend.logic.traces.event import TraceEvent
from products.ai_observability.backend.logic.traces.thread import pick_user_visible_generation
from products.ai_observability.backend.logic.traces.timeline import Timeline
from products.ai_observability.backend.logic.traces.tree import build_tree

from .rows import T0, make_row


def events(*rows: dict[str, Any]) -> list[TraceEvent]:
    return [TraceEvent(row=make_row(**row), trace_id="trace-1") for row in rows]


def rows_of(timeline: Timeline) -> list[tuple[str, int, float, float | None]]:
    return [(row.event.id, row.depth, row.start_ms, row.duration_ms) for row in timeline.rows]


def test_sdk_events_start_at_their_end_minus_latency_and_nest_in_tree_order() -> None:
    timeline = Timeline.from_tree(
        build_tree(
            events(
                {"uuid": "agent", "span_id": "agent", "timestamp": T0 + timedelta(milliseconds=2800), "latency": 2.5},
                {
                    "uuid": "gen",
                    "event": "$ai_generation",
                    "parent_id": "agent",
                    "timestamp": T0 + timedelta(milliseconds=1500),
                    "latency": 1.0,
                },
            ),
            "trace-1",
        )
    )

    assert rows_of(timeline) == [("agent", 0, 0.0, 2500.0), ("gen", 1, 200.0, 1000.0)]
    assert timeline.total_ms == 2500.0


def test_mixes_otel_start_timestamps_with_sdk_end_timestamps() -> None:
    timeline = Timeline.from_tree(
        build_tree(
            events(
                {"uuid": "otel", "timestamp": T0, "latency": 1.0, "ingestion_source": "otel"},
                {"uuid": "sdk", "timestamp": T0 + timedelta(seconds=3), "latency": 1.0},
            ),
            "trace-1",
        )
    )

    assert rows_of(timeline) == [("otel", 0, 0.0, 1000.0), ("sdk", 0, 2000.0, 1000.0)]


def test_latency_less_events_are_instant_markers() -> None:
    timeline = Timeline.from_tree(build_tree(events({"uuid": "marker"}), "trace-1"))

    assert rows_of(timeline) == [("marker", 0, 0.0, None)]
    assert timeline.total_ms == 0.0


def test_empty_tree_has_an_empty_timeline() -> None:
    assert Timeline.from_tree(()) == Timeline(rows=(), total_ms=0.0)


def test_thread_picks_the_latest_generation_and_ignores_newer_non_generations() -> None:
    picked = pick_user_visible_generation(
        events(
            {"uuid": "g2", "event": "$ai_generation", "timestamp": T0 + timedelta(seconds=2)},
            {"uuid": "g3", "event": "$ai_generation", "timestamp": T0 + timedelta(seconds=3)},
            {"uuid": "g1", "event": "$ai_generation", "timestamp": T0 + timedelta(seconds=1)},
            {"uuid": "span", "timestamp": T0 + timedelta(seconds=9)},
        )
    )

    assert picked is not None and picked.id == "g3"


def test_thread_is_empty_without_generations() -> None:
    assert pick_user_visible_generation(events({"uuid": "span"})) is None
