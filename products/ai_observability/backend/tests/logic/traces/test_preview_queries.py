from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized
from rest_framework.exceptions import APIException

from posthog.exceptions import (
    ClickHouseAtCapacity,
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.models import Team
from posthog.models.ai_events.test_util import bulk_create_ai_events

from products.ai_observability.backend.logic.message_normalizer.values import Value
from products.ai_observability.backend.logic.traces import trace_queries
from products.ai_observability.backend.logic.traces.preview_queries import (
    PREVIEW_SOURCE_MAX_BYTES,
    PREVIEWS_QUERY_NAME,
    load_preview_event_rows,
    load_preview_sources,
    load_preview_values,
)
from products.ai_observability.backend.logic.traces.previews import PreviewReads, PreviewSource, TracePreviewSources
from products.ai_observability.backend.logic.traces.turn import TIMED_OUT, TOO_LARGE, Side

T0 = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
OVERSIZED = "x" * (PREVIEW_SOURCE_MAX_BYTES + 1)


def _event_id(index: int) -> str:
    return f"00000000-0000-4000-8000-{index:012d}"


def _message(role: str, text: str) -> dict[str, str]:
    return {"role": role, "content": text}


def _read(value: Value) -> Side[Value]:
    return Side(value=value, unread=None)


SIX_MESSAGES = [_message("user" if index % 2 == 0 else "assistant", f"turn {index}") for index in range(6)]


class TestPreviewQueries(ClickhouseTestMixin, BaseTest):
    def _seed(self, *events: tuple[str, str, Mapping[str, object]], team: Team | None = None) -> None:
        bulk_create_ai_events(
            [
                {
                    "event": event,
                    "event_uuid": _event_id(index),
                    "distinct_id": "user-1",
                    "team": team or self.team,
                    "timestamp": T0 + timedelta(minutes=index),
                    "properties": {"$ai_trace_id": trace_id, "$ai_parent_id": trace_id, **properties},
                }
                for index, (trace_id, event, properties) in enumerate(events)
            ]
        )

    def _sources(self, trace_id: str = "trace-1") -> TracePreviewSources:
        return load_preview_sources(self.team, self.user, [trace_id])[trace_id]

    def test_the_first_generation_gives_its_input_and_the_latest_its_output(self) -> None:
        self._seed(
            *(
                (
                    "trace-1",
                    "$ai_generation",
                    {
                        "$ai_input": [_message("user", f"question {n}")],
                        "$ai_output_choices": [_message("assistant", f"answer {n}")],
                    },
                )
                for n in range(3)
            )
        )

        assert self._sources() == TracePreviewSources(
            state=None,
            first_generation=PreviewSource(
                event_id=_event_id(0),
                kind="generation",
                input=_read([_message("user", "question 0")]),
                output=_read(None),
            ),
            latest_generation=PreviewSource(
                event_id=_event_id(2),
                kind="generation",
                input=_read(None),
                output=_read([_message("assistant", "answer 2")]),
            ),
        )

    def test_a_single_generation_gives_both_sides_from_one_source(self) -> None:
        self._seed(
            ("trace-1", "$ai_generation", {"$ai_input": [_message("user", "hi")], "$ai_output": "hello"}),
        )

        sources = self._sources()

        assert sources.first_generation == PreviewSource(
            event_id=_event_id(0), kind="generation", input=_read([_message("user", "hi")]), output=_read("hello")
        )
        assert sources.latest_generation == sources.first_generation

    @parameterized.expand(
        [
            ("a long conversation keeps its last four messages", SIX_MESSAGES, _read(SIX_MESSAGES[-4:])),
            ("an object under the cap is kept whole", {"prompt": "hi"}, _read({"prompt": "hi"})),
            ("an object over the cap is too large", {"prompt": OVERSIZED}, Side(value=None, unread=TOO_LARGE)),
            (
                "a list over the cap in total keeps its small last four",
                [_message("user", OVERSIZED), *SIX_MESSAGES[:4]],
                _read(SIX_MESSAGES[:4]),
            ),
            (
                "an oversized last item leaves nothing and is too large",
                [*SIX_MESSAGES[:3], _message("user", OVERSIZED)],
                Side(value=[], unread=TOO_LARGE),
            ),
            (
                "an oversized item keeps only what follows it",
                [*SIX_MESSAGES[:2], _message("user", OVERSIZED), SIX_MESSAGES[3]],
                Side(value=[SIX_MESSAGES[3]], unread=TOO_LARGE),
            ),
            (
                "a null last item is read like any other",
                [*SIX_MESSAGES[:3], None],
                _read([*SIX_MESSAGES[:3], None]),
            ),
        ]
    )
    def test_the_input_tail(self, _name: str, input_value: object, expected: Side[Value]) -> None:
        self._seed(("trace-1", "$ai_generation", {"$ai_input": input_value}))

        source = self._sources().first_generation

        assert source is not None and source.input == expected

    @parameterized.expand(
        [
            (
                "choices win over output",
                {"$ai_output_choices": [_message("assistant", "chosen")], "$ai_output": "plain"},
                _read([_message("assistant", "chosen")]),
            ),
            ("output is used without choices", {"$ai_output": "plain"}, _read("plain")),
            (
                "choices over the cap are too large and output does not stand in",
                {"$ai_output_choices": [OVERSIZED], "$ai_output": "plain"},
                Side(value=None, unread=TOO_LARGE),
            ),
        ]
    )
    def test_the_output(self, _name: str, properties: dict[str, object], expected: Side[Value]) -> None:
        self._seed(("trace-1", "$ai_generation", properties))

        source = self._sources().latest_generation

        assert source is not None and source.output == expected

    @parameterized.expand(
        [
            (
                "a trace event with state is the state source",
                {"$ai_input_state": {"messages": ["hi"]}, "$ai_output_state": {"reply": "hello"}},
                PreviewSource(
                    event_id=_event_id(0),
                    kind="trace",
                    input=_read({"messages": ["hi"]}),
                    output=_read({"reply": "hello"}),
                ),
            ),
            (
                "a side without state reads the trace event's other properties",
                {"$ai_input": "plain question", "$ai_output_state": {"reply": "hello"}},
                PreviewSource(
                    event_id=_event_id(0),
                    kind="trace",
                    input=_read("plain question"),
                    output=_read({"reply": "hello"}),
                ),
            ),
            (
                "a state over the cap is too large and the other properties do not stand in",
                {
                    "$ai_input_state": {"document": OVERSIZED},
                    "$ai_input": "plain question",
                    "$ai_output_state": {"a": 1},
                },
                PreviewSource(
                    event_id=_event_id(0),
                    kind="trace",
                    input=Side(value=None, unread=TOO_LARGE),
                    output=_read({"a": 1}),
                ),
            ),
            ("a trace event with empty state is not", {"$ai_input_state": {}}, None),
        ]
    )
    def test_the_state_source(self, _name: str, properties: dict[str, object], expected: PreviewSource | None) -> None:
        self._seed(("trace-1", "$ai_trace", properties), ("trace-1", "$ai_generation", {"$ai_output": "done"}))

        assert self._sources().state == expected

    def test_the_later_of_two_state_events_is_the_state_source(self) -> None:
        self._seed(
            ("trace-1", "$ai_trace", {"$ai_input_state": {"step": "first"}}),
            ("trace-1", "$ai_trace", {"$ai_input_state": {"step": "second"}}),
        )

        assert self._sources().state == PreviewSource(
            event_id=_event_id(1), kind="trace", input=_read({"step": "second"}), output=_read(None)
        )

    def test_another_teams_trace_and_an_unknown_id_have_no_entry(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        self._seed(("shared", "$ai_generation", {"$ai_input": "secret"}), team=other_team)

        with self.capture_select_queries() as queries:
            loaded = load_preview_sources(self.team, self.user, ["shared", "unknown"])

        assert (loaded, len(queries)) == ({}, 1)

    def test_the_light_read_returns_only_the_earliest_and_latest_events(self) -> None:
        self._seed(
            ("trace-1", "$ai_trace", {"$ai_input_state": {"step": "planned"}}),
            *(("trace-1", "$ai_generation", {"$ai_input": f"step {n}"}) for n in range(5)),
        )

        rows = load_preview_event_rows(self.team, self.user, ["trace-1"])

        assert {row.uuid for row in rows} == {_event_id(0), _event_id(1), _event_id(5)}

    def test_a_full_page_picks_each_traces_first_and_latest_generation(self) -> None:
        trace_ids = [f"trace-{n}" for n in range(50)]
        self._seed(
            *(
                event
                for trace_id in trace_ids
                for event in (
                    (trace_id, "$ai_trace", {"$ai_input_state": {"step": "planned"}}),
                    (trace_id, "$ai_generation", {"$ai_input": f"question of {trace_id}", "$ai_output": "first"}),
                    (trace_id, "$ai_generation", {"$ai_input": "follow-up", "$ai_output": f"answer of {trace_id}"}),
                )
            )
        )

        loaded = load_preview_sources(self.team, self.user, trace_ids)

        assert {
            trace_id: (
                sources.first_generation.input.value if sources.first_generation else None,
                sources.latest_generation.output.value if sources.latest_generation else None,
            )
            for trace_id, sources in loaded.items()
        } == {trace_id: (f"question of {trace_id}", f"answer of {trace_id}") for trace_id in trace_ids}

    def test_the_heavy_read_names_only_the_picked_events(self) -> None:
        self._seed(*(("trace-1", "$ai_generation", {"$ai_input": f"step {n}"}) for n in range(5)))

        with self.capture_select_queries() as queries:
            load_preview_sources(self.team, self.user, ["trace-1"])

        [heavy] = [query for query in queries if "JSONExtractArrayRaw" in query]
        assert {_event_id(n) for n in range(5) if _event_id(n) in heavy} == {_event_id(0), _event_id(4)}

    def test_both_reads_fail_instead_of_returning_partial_rows_past_their_deadline(self) -> None:
        self._seed(("trace-1", "$ai_generation", {"$ai_input": "hi", "$ai_output": "hello"}))

        with self.capture_select_queries() as queries:
            load_preview_sources(self.team, self.user, ["trace-1"])

        assert len(queries) == 2
        assert all("timeout_overflow_mode='throw'" in query for query in queries)

    def _sources_when_the_heavy_read_raises(self, error: type[APIException]) -> TracePreviewSources:
        self._seed(
            ("trace-1", "$ai_trace", {"$ai_input_state": {"step": "planned"}}),
            ("trace-1", "$ai_generation", {"$ai_input": "hi", "$ai_output": "hello"}),
        )
        execute = trace_queries.execute_hogql_query

        def heavy_read_raises(*args: Any, **kwargs: Any) -> Any:
            if kwargs["query_type"] == PREVIEWS_QUERY_NAME:
                raise error()
            return execute(*args, **kwargs)

        with patch.object(trace_queries, "execute_hogql_query", side_effect=heavy_read_raises):
            return self._sources()

    @parameterized.expand(
        [
            ("ran out of time", ClickHouseQueryTimeOut),
            ("would run out of time", ClickHouseEstimatedQueryExecutionTimeTooLong),
        ]
    )
    def test_a_heavy_read_out_of_time_times_out_every_picked_side(
        self, _name: str, timeout: type[APIException]
    ) -> None:
        sources = self._sources_when_the_heavy_read_raises(timeout)

        timed_out = Side(value=None, unread=TIMED_OUT)
        generation = PreviewSource(event_id=_event_id(1), kind="generation", input=timed_out, output=timed_out)
        assert sources == TracePreviewSources(
            state=PreviewSource(event_id=_event_id(0), kind="trace", input=timed_out, output=timed_out),
            first_generation=generation,
            latest_generation=generation,
        )

    @parameterized.expand(
        [
            ("out of memory", ClickHouseQueryMemoryLimitExceeded),
            ("at capacity", ClickHouseAtCapacity),
        ]
    )
    def test_a_heavy_read_failing_otherwise_fails_the_read(self, _name: str, error: type[APIException]) -> None:
        with self.assertRaises(error):
            self._sources_when_the_heavy_read_raises(error)

    def test_the_heavy_read_returns_only_each_events_role(self) -> None:
        self._seed(
            ("trace-1", "$ai_generation", {"$ai_input": "first question", "$ai_output": "first answer"}),
            ("trace-1", "$ai_generation", {"$ai_input": "latest question", "$ai_output": "latest answer"}),
        )
        first, latest = _event_id(0), _event_id(1)

        read = load_preview_values(
            self.team,
            self.user,
            PreviewReads(trace_ids=("trace-1",), input_ids=(first,), output_ids=(latest,), state_ids=()),
        )

        assert {
            uuid: {name: stored.value for name, stored in event.values.items()} for uuid, event in read.items()
        } == {
            first: {
                "$ai_input": "first question",
                "$ai_output_choices": None,
                "$ai_output": None,
                "$ai_input_state": None,
                "$ai_output_state": None,
            },
            latest: {
                "$ai_input": None,
                "$ai_output_choices": None,
                "$ai_output": "latest answer",
                "$ai_input_state": None,
                "$ai_output_state": None,
            },
        }
