import json
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_person

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.models import Team
from posthog.models.ai_events.sql import AI_EVENTS_MV_SQL
from posthog.models.ai_events.test_util import bulk_create_ai_events
from posthog.models.event.util import bulk_create_events

from products.ai_observability.backend.logic.traces.trace_queries import (
    TraceRootLookup,
    is_truthy_json,
    load_trace,
    load_trace_node,
    load_trace_root,
)

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
INGESTED_SOURCE = """(
    SELECT
        toUUID(%(uuid)s) AS uuid,
        %(event)s AS event,
        toDateTime64(%(timestamp)s, 6, 'UTC') AS timestamp,
        %(team_id)s AS team_id,
        'user-1' AS distinct_id,
        generateUUIDv4() AS person_id,
        %(properties)s AS properties,
        now() AS _timestamp,
        0 AS _offset,
        0 AS _partition
)"""


@parameterized.expand(
    [
        ("missing", "", False),
        ("null", "null", False),
        ("empty string", '""', False),
        ("false", "false", False),
        ("zero", "0", False),
        ("empty array", "[]", False),
        ("empty object", "{}", False),
        ("text", '"boom"', True),
        ("text that reads null", '"null"', True),
        ("true", "true", True),
        ("non-zero number", "-1.5", True),
        ("array", '["boom"]', True),
        ("object", '{"message": "boom"}', True),
    ]
)
def test_is_truthy_json(_name: str, raw: str, expected: bool) -> None:
    assert is_truthy_json(raw) is expected


class TraceEventsMixin:
    team: Team

    def _event(
        self,
        uuid: str,
        *,
        trace_id: str = "trace-1",
        event: str = "$ai_span",
        timestamp: datetime = T0,
        properties: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return {
            "event": event,
            "event_uuid": uuid,
            "distinct_id": "user-1",
            "team": self.team,
            "timestamp": timestamp,
            "properties": {"$ai_trace_id": trace_id, **(properties or {})},
        }

    def _ingest(self, uuid: str, properties: dict[str, object], *, event: str = "$ai_span") -> None:
        # Goes through the materialized view expressions, because bulk_create_ai_events types columns differently.
        mv_select = AI_EVENTS_MV_SQL(kafka_table=INGESTED_SOURCE).split("AS SELECT", 1)[1]
        params = {
            "uuid": uuid,
            "event": event,
            "timestamp": T0.strftime("%Y-%m-%d %H:%M:%S.%f"),
            "team_id": self.team.pk,
            "properties": json.dumps({"$ai_trace_id": "trace-1", **properties}),
        }
        columns = ", ".join(row[0] for row in sync_execute(f"DESCRIBE TABLE (SELECT {mv_select})", params))
        sync_execute(
            f"INSERT INTO sharded_ai_events ({columns}, retention_days) SELECT *, 10000 FROM (SELECT {mv_select})",
            params,
            flush=False,
        )


class TestLoadTrace(TraceEventsMixin, ClickhouseTestMixin, BaseTest):
    def test_reads_every_event_once_and_only_this_trace(self) -> None:
        uuids = [f"00000000-0000-0000-0000-{index:012d}" for index in range(150)]
        failed = self._event(uuids[0], properties={"$ai_latency": 1.0, "$ai_error": {"message": "boom"}})
        rows = [self._event(uuid, properties={"$ai_latency": 1.0}) for uuid in uuids[1:]]
        bulk_create_ai_events(
            [failed, *rows, failed, self._event("00000000-0000-0000-0001-000000000000", trace_id="other")]
        )

        loaded = load_trace(self.team, None, "trace-1", None)

        assert sorted(row.uuid for row in loaded.rows) == uuids
        assert loaded.rows[0].latency == 1.0
        assert [row.uuid for row in loaded.rows if row.error_is_truthy] == [uuids[0]]

    def test_ingested_error_and_token_values_read_like_the_legacy_view(self) -> None:
        self._ingest("00000000-0000-0000-0000-000000000001", {"$ai_error": "", "$ai_input_tokens": {"total": 7}})
        self._ingest("00000000-0000-0000-0000-000000000002", {"$ai_error": {"message": "boom"}, "$ai_input_tokens": 3})

        rows = load_trace(self.team, None, "trace-1", None).rows

        assert sorted((row.uuid, row.error_is_truthy, row.input_tokens) for row in rows) == [
            ("00000000-0000-0000-0000-000000000001", False, 7),
            ("00000000-0000-0000-0000-000000000002", True, 3),
        ]

    def test_person_comes_from_the_trace_event_distinct_id(self) -> None:
        _create_person(distinct_ids=["user-1"], team=self.team, properties={"email": "ada@example.com"})
        _create_person(distinct_ids=["user-2"], team=self.team, properties={"email": "grace@example.com"})
        earlier_span = {**self._event("00000000-0000-0000-0000-000000000002"), "distinct_id": "user-2"}
        trace_event = self._event(
            "00000000-0000-0000-0000-000000000001", event="$ai_trace", timestamp=T0 + timedelta(seconds=1)
        )
        bulk_create_ai_events([earlier_span, trace_event])

        person = load_trace(self.team, None, "trace-1", None).person

        assert person is not None and (person.distinct_id, person.email) == ("user-1", "ada@example.com")


NODE = "00000000-0000-0000-0000-000000000001"
TRACE_EVENT = "00000000-0000-0000-0000-000000000002"
QUESTION = [{"role": "user", "content": "Why did my invoice go up?"}]
ANSWER = [{"role": "assistant", "content": "Two seats were added."}]


class TestLoadTraceNode(TraceEventsMixin, ClickhouseTestMixin, BaseTest):
    def test_merges_the_heavy_columns_back_into_the_properties(self) -> None:
        self._ingest(
            NODE,
            {"$ai_input": QUESTION, "$ai_output_choices": ANSWER, "$ai_model": "gpt-4.1-mini"},
            event="$ai_generation",
        )

        row = load_trace_node(self.team, None, "trace-1", NODE, None)

        assert row is not None
        assert (row.uuid, row.event) == (NODE, "$ai_generation")
        assert (row.properties["$ai_input"], row.properties["$ai_output_choices"]) == (QUESTION, ANSWER)
        assert row.properties["$ai_model"] == "gpt-4.1-mini"

    @parameterized.expand(
        [
            ("an annotation", "$ai_feedback", "trace-1", NODE),
            ("a node of another trace", "$ai_span", "other", NODE),
            ("an id that is not an event uuid", "$ai_span", "trace-1", "gen_8f2c"),
        ]
    )
    def test_finds_nothing_for(self, _name: str, event: str, trace_id: str, requested: str) -> None:
        bulk_create_ai_events([self._event(NODE, trace_id=trace_id, event=event)])

        assert load_trace_node(self.team, None, "trace-1", requested, None) is None

    def test_root_reads_the_trace_event_even_when_other_events_come_first(self) -> None:
        bulk_create_ai_events(
            [
                self._event(NODE, timestamp=T0),
                self._event(
                    TRACE_EVENT,
                    event="$ai_trace",
                    timestamp=T0 + timedelta(seconds=5),
                    properties={"$ai_input_state": {"question": "x"}},
                ),
            ]
        )

        root = load_trace_root(self.team, None, "trace-1", None)

        assert root.trace_found and root.trace_event is not None
        assert (root.trace_event.uuid, root.trace_event.properties["$ai_input_state"]) == (
            TRACE_EVENT,
            {"question": "x"},
        )

    @parameterized.expand([("a trace without a trace event", True), ("an unknown trace", False)])
    def test_root_without_a_trace_event(self, _name: str, has_events: bool) -> None:
        if has_events:
            bulk_create_ai_events([self._event(NODE)])

        assert load_trace_root(self.team, None, "trace-1", None) == TraceRootLookup(
            trace_event=None, trace_found=has_events
        )

    def test_node_id_matches_however_the_uuid_is_written(self) -> None:
        bulk_create_ai_events([self._event(NODE)])

        row = load_trace_node(self.team, None, "trace-1", NODE.upper().replace("-", ""), None)

        assert row is not None and row.uuid == NODE


class TestEventsFallback(TraceEventsMixin, ClickhouseTestMixin, BaseTest):
    @parameterized.expand([("with a hint", T0), ("without a hint", None)])
    def test_falls_back_to_events(self, _name: str, timestamp_hint: datetime | None) -> None:
        old_span: dict[str, object] = {"$ai_span_name": "old", "$ai_error": {"message": "boom"}}
        clean_span: dict[str, object] = {"$ai_error": "", "$ai_input_tokens": {"total": 7}}
        bulk_create_events(
            [
                self._event("00000000-0000-0000-0000-000000000001", properties=old_span),
                self._event("00000000-0000-0000-0000-000000000002", properties=clean_span),
            ]
        )

        loaded = load_trace(self.team, None, "trace-1", timestamp_hint)

        assert sorted((row.uuid, row.span_name, row.error_is_truthy, row.input_tokens) for row in loaded.rows) == [
            ("00000000-0000-0000-0000-000000000001", "old", True, None),
            ("00000000-0000-0000-0000-000000000002", None, False, 7),
        ]

    def test_hint_bounds_the_fallback_window(self) -> None:
        bulk_create_events([self._event("00000000-0000-0000-0000-000000000001")])

        assert load_trace(self.team, None, "trace-1", T0 + timedelta(minutes=11)).rows == ()

    def test_unhinted_fallback_starts_at_the_legacy_default_range(self) -> None:
        bulk_create_events(
            [self._event("00000000-0000-0000-0000-000000000001", timestamp=datetime(2025, 1, 9, tzinfo=UTC))]
        )

        assert load_trace(self.team, None, "trace-1", None).rows == ()

    def test_node_and_root_fall_back_to_events(self) -> None:
        bulk_create_events(
            [
                self._event(NODE, properties={"$ai_span_name": "old"}),
                self._event(TRACE_EVENT, event="$ai_trace", timestamp=T0 + timedelta(seconds=1)),
            ]
        )

        row = load_trace_node(self.team, None, "trace-1", NODE, T0)
        root = load_trace_root(self.team, None, "trace-1", T0)

        assert row is not None and row.properties["$ai_span_name"] == "old"
        assert root.trace_event is not None and root.trace_event.uuid == TRACE_EVENT

    def test_node_and_root_without_a_hint_never_scan_events(self) -> None:
        bulk_create_events([self._event(NODE), self._event(TRACE_EVENT, event="$ai_trace")])

        assert load_trace_node(self.team, None, "trace-1", NODE, None) is None
        assert load_trace_root(self.team, None, "trace-1", None) == TraceRootLookup(trace_event=None, trace_found=False)
