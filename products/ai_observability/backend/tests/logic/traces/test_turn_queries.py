from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from posthog.exceptions import ClickHouseQueryTimeOut
from posthog.models.ai_events.test_util import bulk_create_ai_events
from posthog.models.event.new_events_schema import use_new_events_schema
from posthog.models.event.util import bulk_create_events

from products.ai_observability.backend.logic.message_normalizer.values import Value
from products.ai_observability.backend.logic.traces import trace_queries
from products.ai_observability.backend.logic.traces.preview_queries import PREVIEW_SOURCE_MAX_BYTES
from products.ai_observability.backend.logic.traces.previews import PreviewSource
from products.ai_observability.backend.logic.traces.turn import TIMED_OUT, TOO_LARGE, Side
from products.ai_observability.backend.logic.traces.turn_queries import (
    TURN_INPUT_ITEMS,
    TURNS_QUERY_NAME,
    TurnSources,
    load_turn_sources,
)

T0 = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
OVERSIZED = "x" * (PREVIEW_SOURCE_MAX_BYTES + 1)


def _event_id(index: int) -> str:
    return f"00000000-0000-4000-8000-{index:012d}"


def _message(role: str, text: str) -> dict[str, str]:
    return {"role": role, "content": text}


def _read(value: Value) -> Side[Value]:
    return Side(value=value, unread=None)


class TestTurnQueries(ClickhouseTestMixin, BaseTest):
    def _events(self, *events: tuple[str, str, Mapping[str, object]]) -> list[dict[str, Any]]:
        return [
            {
                "event": event,
                "event_uuid": _event_id(index),
                "distinct_id": "user-1",
                "team": self.team,
                "timestamp": T0 + timedelta(minutes=index),
                "properties": {"$ai_trace_id": trace_id, "$ai_parent_id": trace_id, **properties},
            }
            for index, (trace_id, event, properties) in enumerate(events)
        ]

    def _sources(self, trace_id: str = "trace-1") -> TurnSources:
        loaded = load_turn_sources(self.team, self.user, [trace_id], earliest=T0, latest=T0 + timedelta(hours=1))
        return loaded[trace_id]

    def test_reads_latest_generation_input_tail(self) -> None:
        history = [_message("user" if n % 2 == 0 else "assistant", f"turn {n}") for n in range(TURN_INPUT_ITEMS + 5)]
        bulk_create_ai_events(
            self._events(
                ("trace-1", "$ai_generation", {"$ai_input": [_message("user", "opening")]}),
                ("trace-1", "$ai_generation", {"$ai_input": history, "$ai_output": "latest answer"}),
            )
        )

        sources = self._sources()

        assert sources.latest_generation_input == _read(history[-TURN_INPUT_ITEMS:])
        assert sources.first_generation == PreviewSource(
            event_id=_event_id(0), kind="generation", input=_read([_message("user", "opening")]), output=_read(None)
        )
        assert sources.latest_generation == PreviewSource(
            event_id=_event_id(1),
            kind="generation",
            input=_read(history[-TURN_INPUT_ITEMS:]),
            output=_read("latest answer"),
        )

    def test_a_single_generation_gives_the_same_input_as_first_and_latest(self) -> None:
        bulk_create_ai_events(
            self._events(("trace-1", "$ai_generation", {"$ai_input": [_message("user", "hi")], "$ai_output": "yo"}))
        )

        sources = self._sources()

        assert sources.first_generation is not None
        assert sources.latest_generation_input == sources.first_generation.input == _read([_message("user", "hi")])

    def test_a_trace_without_a_generation_has_no_latest_input(self) -> None:
        bulk_create_ai_events(self._events(("trace-1", "$ai_trace", {"$ai_input_state": {"step": "planned"}})))

        sources = self._sources()

        assert (sources.first_generation, sources.latest_generation, sources.latest_generation_input) == (
            None,
            None,
            None,
        )
        assert sources.state == PreviewSource(
            event_id=_event_id(0), kind="trace", input=_read({"step": "planned"}), output=_read(None)
        )

    def test_item_over_cap_marks_too_large(self) -> None:
        bulk_create_ai_events(
            self._events(
                (
                    "trace-1",
                    "$ai_generation",
                    {"$ai_input": [_message("user", OVERSIZED), _message("user", "kept"), _message("user", "last")]},
                ),
            )
        )

        assert self._sources().latest_generation_input == Side(
            value=[_message("user", "kept"), _message("user", "last")], unread=TOO_LARGE
        )

    def test_trace_past_retention_read_from_events(self) -> None:
        bulk_create_events(
            self._events(("aged", "$ai_generation", {"$ai_input": [_message("user", "hi")], "$ai_output": "hello"}))
        )

        sources = self._sources("aged")

        heavy_properties_kept = not use_new_events_schema(self.team.pk)
        generation = PreviewSource(
            event_id=_event_id(0),
            kind="generation",
            input=_read([_message("user", "hi")] if heavy_properties_kept else None),
            output=_read("hello" if heavy_properties_kept else None),
        )
        assert sources == TurnSources(
            state=None,
            first_generation=generation,
            latest_generation=generation,
            latest_generation_input=generation.input,
        )

    def test_a_trace_in_ai_events_is_not_read_from_events_again(self) -> None:
        bulk_create_ai_events(self._events(("here", "$ai_generation", {"$ai_input": "from ai_events"})))
        bulk_create_events(self._events(("here", "$ai_generation", {"$ai_input": "from events"})))

        with self.capture_select_queries() as queries:
            sources = self._sources("here")

        assert sources.latest_generation_input == _read("from ai_events")
        assert len(queries) == 2

    def test_timeout_marks_every_side(self) -> None:
        bulk_create_ai_events(
            self._events(
                ("trace-1", "$ai_trace", {"$ai_input_state": {"step": "planned"}}),
                ("trace-1", "$ai_generation", {"$ai_input": "hi", "$ai_output": "hello"}),
            )
        )
        execute = trace_queries.execute_hogql_query

        def heavy_read_times_out(*args: Any, **kwargs: Any) -> Any:
            if kwargs["query_type"] == TURNS_QUERY_NAME:
                raise ClickHouseQueryTimeOut()
            return execute(*args, **kwargs)

        with patch.object(trace_queries, "execute_hogql_query", side_effect=heavy_read_times_out):
            sources = self._sources()

        timed_out = Side(value=None, unread=TIMED_OUT)
        generation = PreviewSource(event_id=_event_id(1), kind="generation", input=timed_out, output=timed_out)
        assert sources == TurnSources(
            state=PreviewSource(event_id=_event_id(0), kind="trace", input=timed_out, output=timed_out),
            first_generation=generation,
            latest_generation=generation,
            latest_generation_input=timed_out,
        )
