import re
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_person
from unittest.mock import patch

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.models import Team
from posthog.models.ai_events.sql import AI_EVENTS_MV_SQL
from posthog.models.ai_events.test_util import bulk_create_ai_events
from posthog.models.event.util import bulk_create_events
from posthog.models.person.util import create_person_distinct_id
from posthog.test.persons import add_distinct_id, create_person, delete_person

from products.ai_observability.backend.logic.traces import trace_queries
from products.ai_observability.backend.logic.traces.events_fallback import (
    FallbackWindow,
    fallback_window,
    unhinted_window,
)
from products.ai_observability.backend.logic.traces.person import person_label
from products.ai_observability.backend.logic.traces.trace_queries import (
    GitStampRow,
    LoadedTrace,
    PageTraceRows,
    PersonRow,
    SearchNeedles,
    TraceRootLookup,
    load_people,
    load_trace,
    load_trace_distinct_ids,
    load_trace_feedback_rows,
    load_trace_git_rows,
    load_trace_node,
    load_trace_root,
    load_trace_search,
    load_traces_rows,
    rows_per_trace_cap,
)

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
GENERATION = "00000000-0000-0000-0000-0000000000a1"
SPAN = "00000000-0000-0000-0000-0000000000a2"
INGESTED_SOURCE = """(
    SELECT
        toUUID(%(uuid)s) AS uuid,
        %(event)s AS event,
        toDateTime64(%(timestamp)s, 6, 'UTC') AS timestamp,
        %(team_id)s AS team_id,
        'user-1' AS distinct_id,
        generateUUIDv4() AS person_id,
        %(properties)s AS properties,
        CAST([], 'Array(String)') AS `_headers.name`,
        CAST([], 'Array(String)') AS `_headers.value`,
        now() AS _timestamp,
        0 AS _offset,
        0 AS _partition
)"""


@parameterized.expand(
    [
        ("plain text", "invoice", "invoice", ("invoice",)),
        ("a double quote", 'say "hi"', 'say "hi"', ('say \\"hi\\"', 'say \\\\\\"hi\\\\\\"')),
        ("a backslash", "C:\\tmp", "C:\\tmp", ("C:\\\\tmp", "C:\\\\\\\\tmp")),
        ("non-ASCII text", "café", "café", ("café", "caf\\\\u00e9")),
    ]
)
def test_search_needles_match_text_and_stored_json(
    _name: str, query: str, text: str, json_needles: tuple[str, ...]
) -> None:
    assert SearchNeedles.of(query) == SearchNeedles(text=text, json=json_needles)


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
        distinct_id: str = "user-1",
    ) -> dict[str, object]:
        return {
            "event": event,
            "event_uuid": uuid,
            "distinct_id": distinct_id,
            "team": self.team,
            "timestamp": timestamp,
            "properties": {"$ai_trace_id": trace_id, **(properties or {})},
        }

    def _list_row_events(self) -> list[dict[str, object]]:
        generation_properties: dict[str, object] = {
            "$ai_tools_called": "search, fetch",
            "$ai_error": {"message": "boom"},
            "$ai_is_error": True,
            "ai_support_impersonated": True,
        }
        return [
            self._event(GENERATION, event="$ai_generation", properties=generation_properties),
            self._event(SPAN, event="$ai_span"),
        ]

    def _assert_list_row_columns(self, loaded: LoadedTrace) -> None:
        by_uuid = {row.uuid: row for row in loaded.rows}

        generation, span = by_uuid[GENERATION], by_uuid[SPAN]

        assert (generation.tools_called, generation.error_text, generation.is_support) == (
            ("search", "fetch"),
            '{"message": "boom"}',
            True,
        )
        assert (span.tools_called, span.error_text, span.is_support) == ((), None, False)

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
            f"INSERT INTO sharded_ai_events ({columns}) SELECT * REPLACE (10000 AS retention_days) FROM (SELECT {mv_select})",
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
        assert loaded.read_start is None

    def test_reads_the_columns_a_list_row_needs(self) -> None:
        bulk_create_ai_events(self._list_row_events())

        self._assert_list_row_columns(load_trace(self.team, None, "trace-1", None))

    def test_trace_totals_cover_the_whole_trace(self) -> None:
        _create_person(distinct_ids=["root-user"], team=self.team, properties={"email": "ada@example.com"})
        generations = [
            self._event(
                _uuid(index),
                event="$ai_generation",
                timestamp=T0 + timedelta(seconds=index),
                properties={"$ai_latency": 1.5, "$ai_total_cost_usd": 0.25},
            )
            for index in range(4)
        ]
        root = self._event(
            _uuid(4),
            event="$ai_trace",
            timestamp=T0 + timedelta(seconds=4),
            distinct_id="root-user",
            properties={"$ai_session_id": "session-1"},
        )
        bulk_create_ai_events([*generations, root])

        with patch.object(trace_queries, "MAX_TRACE_EVENTS", 3):
            loaded = load_trace(self.team, None, "trace-1", None)

        assert len(loaded.rows) == 3
        assert {(row.trace_latency_s, row.trace_cost_usd, row.trace_session_id) for row in loaded.rows} == {
            (6.0, 1.0, "session-1")
        }
        assert loaded.person == PersonRow(distinct_id="root-user", display_name="ada@example.com")

    def test_ingested_values_read_like_the_legacy_view(self) -> None:
        self._ingest(
            "00000000-0000-0000-0000-000000000001",
            {
                "$ai_error": "",
                "$ai_input_tokens": {"total": 7},
                "$ai_input_state": None,
                "$ai_output_state": {},
                "$ai_git_branch": "",
            },
            event="$ai_trace",
        )
        self._ingest(
            "00000000-0000-0000-0000-000000000002",
            {
                "$ai_error": {"message": "boom"},
                "$ai_input_tokens": 3,
                "$ai_output_state": {"answer": "hi"},
                "$ai_git_branch": "feat/rag",
                "$ai_git_repo": "acme/app",
            },
            event="$ai_trace",
        )

        rows = load_trace(self.team, None, "trace-1", None).rows

        assert sorted(
            (row.uuid, row.error_is_truthy, row.input_tokens, row.has_state, row.git_branch, row.git_repo)
            for row in rows
        ) == [
            ("00000000-0000-0000-0000-000000000001", False, 7, False, None, None),
            ("00000000-0000-0000-0000-000000000002", True, 3, True, "feat/rag", "acme/app"),
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

        assert person == PersonRow(distinct_id="user-1", display_name="ada@example.com")

    def test_reads_no_feedback_or_metric_events(self) -> None:
        bulk_create_ai_events(
            [
                self._event(
                    "00000000-0000-0000-0000-000000000001",
                    event="$ai_feedback",
                    timestamp=T0 - timedelta(seconds=1),
                    properties={"$ai_feedback_text": "Too long, but correct."},
                ),
                self._event(
                    "00000000-0000-0000-0000-000000000002",
                    event="$ai_metric",
                    properties={"$ai_metric_name": "helpfulness", "$ai_metric_value": 0},
                ),
                self._event("00000000-0000-0000-0000-000000000003", timestamp=T0 + timedelta(seconds=1)),
            ]
        )

        rows = load_trace(self.team, None, "trace-1", None).rows

        assert [row.event for row in rows] == ["$ai_span"]


class TestLoadTraceFeedbackRows(TraceEventsMixin, ClickhouseTestMixin, BaseTest):
    def test_reads_feedback_of_this_trace_and_only_the_steps_it_targets(self) -> None:
        self._ingest(
            "00000000-0000-0000-0000-000000000001",
            {"$ai_metric_name": "helpfulness", "$ai_metric_value": 0, "$ai_parent_id": "span-a"},
            event="$ai_metric",
        )
        self._ingest(
            "00000000-0000-0000-0000-000000000002",
            {"$ai_metric_name": "helpfulness", "$ai_metric_value": "0", "$ai_parent_id": "gen-a"},
            event="$ai_metric",
        )
        self._ingest(
            "00000000-0000-0000-0000-000000000003",
            {"$ai_feedback_text": "Too long, but correct."},
            event="$ai_feedback",
        )
        self._ingest("00000000-0000-0000-0000-000000000004", {"$ai_generation_id": "gen-a"}, event="$ai_generation")
        self._ingest("00000000-0000-0000-0000-000000000005", {}, event="$ai_trace")
        self._ingest("00000000-0000-0000-0000-000000000007", {"$ai_span_id": "span-a"})
        self._ingest("00000000-0000-0000-0000-000000000010", {"$ai_span_id": "span-untargeted"})
        self._ingest(
            "00000000-0000-0000-0000-000000000008",
            {"$ai_metric_value": 2, "$ai_parent_id": "00000000-0000-0000-0000-000000000009"},
            event="$ai_metric",
        )
        self._ingest("00000000-0000-0000-0000-000000000009", {})
        self._ingest(
            "00000000-0000-0000-0000-000000000006",
            {"$ai_trace_id": "other", "$ai_metric_value": 1},
            event="$ai_metric",
        )

        rows = load_trace_feedback_rows(self.team, None, "trace-1", None)

        assert sorted(
            (row.uuid, row.event, row.parent_id, row.generation_id, row.metric_name, row.metric_value_json)
            for row in rows
        ) == [
            ("00000000-0000-0000-0000-000000000001", "$ai_metric", "span-a", None, "helpfulness", "0"),
            ("00000000-0000-0000-0000-000000000002", "$ai_metric", "gen-a", None, "helpfulness", '"0"'),
            ("00000000-0000-0000-0000-000000000003", "$ai_feedback", None, None, None, ""),
            ("00000000-0000-0000-0000-000000000004", "$ai_generation", None, "gen-a", None, ""),
            ("00000000-0000-0000-0000-000000000007", "$ai_span", None, None, None, ""),
            (
                "00000000-0000-0000-0000-000000000008",
                "$ai_metric",
                "00000000-0000-0000-0000-000000000009",
                None,
                None,
                "2",
            ),
            ("00000000-0000-0000-0000-000000000009", "$ai_span", None, None, None, ""),
        ]
        assert [row.feedback_text_json for row in rows if row.event == "$ai_feedback"] == ['"Too long, but correct."']


NODE = "00000000-0000-0000-0000-000000000001"
TRACE_EVENT = "00000000-0000-0000-0000-000000000002"
QUESTION = [{"role": "user", "content": "Why did my invoice go up?"}]
ANSWER = [{"role": "assistant", "content": "Two seats were added."}]


class TestLoadTraceNode(TraceEventsMixin, ClickhouseTestMixin, BaseTest):
    def test_merges_the_heavy_columns_back_into_the_properties(self) -> None:
        self._ingest(
            NODE,
            {"$ai_input": QUESTION, "$ai_output_choices": ANSWER, "$ai_model": "gpt-6-luna"},
            event="$ai_generation",
        )

        row = load_trace_node(self.team, None, "trace-1", NODE, None)

        assert row is not None
        assert (row.uuid, row.event) == (NODE, "$ai_generation")
        assert (row.properties["$ai_input"], row.properties["$ai_output_choices"]) == (QUESTION, ANSWER)
        assert row.properties["$ai_model"] == "gpt-6-luna"

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


class TestLoadTraceGitRows(TraceEventsMixin, ClickhouseTestMixin, BaseTest):
    def test_reads_only_this_traces_stamped_events(self) -> None:
        stamped = "00000000-0000-0000-0000-000000000001"
        bulk_create_ai_events(
            [
                self._event(stamped, properties={"$ai_git_branch": "feat/rag"}),
                self._event("00000000-0000-0000-0000-000000000002"),
                self._event("00000000-0000-0000-0000-000000000003", properties={"$ai_git_branch": ""}),
                self._event(
                    "00000000-0000-0000-0000-000000000004", trace_id="other", properties={"$ai_git_branch": "feat/x"}
                ),
            ]
        )

        assert [row.uuid for row in load_trace_git_rows(self.team, None, "trace-1", T0)] == [stamped]

    def test_reads_stamps_only_from_the_events_the_trace_loads(self) -> None:
        bulk_create_ai_events(
            [
                self._event(NODE, properties={"$ai_git_branch": "feat/one", "$ai_git_repo": "acme/app"}),
                self._event("00000000-0000-0000-0000-000000000002", timestamp=T0 + timedelta(seconds=1)),
                self._event(
                    "00000000-0000-0000-0000-000000000003",
                    timestamp=T0 + timedelta(seconds=2),
                    properties={"$ai_git_branch": "feat/two"},
                ),
            ]
        )

        with patch.object(trace_queries, "MAX_TRACE_EVENTS", 2):
            rows = load_trace_git_rows(self.team, None, "trace-1", T0)

        assert rows == (GitStampRow(uuid=NODE, timestamp=T0, git_branch="feat/one", git_repo="acme/app"),)


class TestEventsFallback(TraceEventsMixin, ClickhouseTestMixin, BaseTest):
    @parameterized.expand([("with a hint", T0), ("without a hint", None)])
    def test_falls_back_to_events(self, _name: str, timestamp_hint: datetime | None) -> None:
        old_span: dict[str, object] = {
            "$ai_span_name": "old",
            "$ai_error": {"message": "boom"},
            "$ai_git_branch": "feat/rag",
        }
        clean_span: dict[str, object] = {"$ai_error": "", "$ai_input_tokens": {"total": 7}, "$ai_output_state": None}
        bulk_create_events(
            [
                self._event("00000000-0000-0000-0000-000000000001", properties=old_span),
                self._event("00000000-0000-0000-0000-000000000002", properties=clean_span),
            ]
        )

        loaded = load_trace(self.team, None, "trace-1", timestamp_hint)

        assert sorted(
            (row.uuid, row.span_name, row.error_is_truthy, row.input_tokens, row.has_state, row.git_branch)
            for row in loaded.rows
        ) == [
            ("00000000-0000-0000-0000-000000000001", "old", True, None, False, "feat/rag"),
            ("00000000-0000-0000-0000-000000000002", None, False, 7, False, None),
        ]
        window = fallback_window(timestamp_hint) if timestamp_hint is not None else unhinted_window()
        assert loaded.read_start == window.start

    def test_falls_back_to_events_for_the_columns_a_list_row_needs(self) -> None:
        bulk_create_events(self._list_row_events())

        self._assert_list_row_columns(load_trace(self.team, None, "trace-1", T0))

    def test_hint_bounds_the_fallback_window(self) -> None:
        bulk_create_events([self._event("00000000-0000-0000-0000-000000000001")])

        assert load_trace(self.team, None, "trace-1", T0 + timedelta(minutes=11)).rows == ()

    def test_unhinted_fallback_starts_at_the_legacy_default_range(self) -> None:
        bulk_create_events(
            [self._event("00000000-0000-0000-0000-000000000001", timestamp=datetime(2025, 1, 9, tzinfo=UTC))]
        )

        assert load_trace(self.team, None, "trace-1", None).rows == ()

    def test_point_reads_fall_back_to_events(self) -> None:
        bulk_create_events(
            [
                self._event(NODE, properties={"$ai_span_name": "old", "$ai_git_branch": "feat/rag"}),
                self._event(TRACE_EVENT, event="$ai_trace", timestamp=T0 + timedelta(seconds=1)),
            ]
        )

        row = load_trace_node(self.team, None, "trace-1", NODE, T0)
        root = load_trace_root(self.team, None, "trace-1", T0)
        git_rows = load_trace_git_rows(self.team, None, "trace-1", T0)

        assert row is not None and row.properties["$ai_span_name"] == "old"
        assert root.trace_event is not None and root.trace_event.uuid == TRACE_EVENT
        assert [(git_row.uuid, git_row.git_branch) for git_row in git_rows] == [(NODE, "feat/rag")]

    @parameterized.expand([("with a hint", T0, 1), ("without a hint", None, 0)])
    def test_feedback_falls_back_to_events_only_with_a_hint(
        self, _name: str, timestamp_hint: datetime | None, expected: int
    ) -> None:
        bulk_create_events(
            [
                self._event(
                    NODE, event="$ai_metric", properties={"$ai_metric_name": "helpfulness", "$ai_metric_value": 0}
                )
            ]
        )

        rows = load_trace_feedback_rows(self.team, None, "trace-1", timestamp_hint)

        assert [(row.metric_name, row.metric_value_json) for row in rows] == [("helpfulness", "0")] * expected

    def test_point_reads_without_a_hint_never_scan_events(self) -> None:
        bulk_create_events(
            [
                self._event(NODE, properties={"$ai_git_branch": "feat/rag"}),
                self._event(TRACE_EVENT, event="$ai_trace"),
            ]
        )

        assert load_trace_node(self.team, None, "trace-1", NODE, None) is None
        assert load_trace_root(self.team, None, "trace-1", None) == TraceRootLookup(trace_event=None, trace_found=False)
        assert load_trace_git_rows(self.team, None, "trace-1", None) == ()

    def test_search_falls_back_to_events_with_a_hint_only(self) -> None:
        bulk_create_events([self._event(NODE, properties={"$ai_span_name": "Fetch invoice"})])

        assert load_trace_search(self.team, None, "trace-1", "invoice", T0).counts == {NODE: 1}
        assert load_trace_search(self.team, None, "trace-1", "invoice", None).rows == ()

    def test_trace_latency_on_events_fallback(self) -> None:
        bulk_create_events(
            [
                self._event(_uuid(1), event="$ai_trace", properties={"$ai_latency": 9.0}),
                self._event(_uuid(2), event="$ai_generation", properties={"$ai_latency": 2.0}),
            ]
        )

        loaded = load_trace(self.team, None, "trace-1", T0)

        assert {row.trace_latency_s for row in loaded.rows} == {9.0}

    def test_a_page_reads_traces_missing_from_ai_events_from_the_shared_table(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        bulk_create_ai_events([self._event(_uuid(1), trace_id="recent")])
        bulk_create_events(
            [
                self._event(_uuid(2), trace_id="aged", properties={"$ai_span_name": "Fetch invoice"}),
                self._event(_uuid(3), trace_id="outside", timestamp=WINDOW.end + timedelta(minutes=1)),
                {**self._event(_uuid(4), trace_id="aged"), "team": other_team},
            ]
        )

        loaded = load_traces_rows(self.team, self.user, ["recent", "aged", "outside"], WINDOW)

        assert _page_uuids(loaded) == {"recent": [_uuid(1)], "aged": [_uuid(2)]}
        assert loaded["aged"].rows[0].span_name == "Fetch invoice"

    def test_a_page_missing_from_ai_events_reads_the_shared_table_once(self) -> None:
        bulk_create_events([self._event(_uuid(1), trace_id="aged")])

        with self.capture_select_queries() as queries:
            loaded = load_traces_rows(self.team, self.user, ["aged", "unknown"], WINDOW)

        assert set(loaded) == {"aged"}
        assert _tables_read(queries) == ["ai_events", "events"]


SPAN = "00000000-0000-0000-0000-000000000011"
GENERATION = "00000000-0000-0000-0000-000000000012"
QUIET_GENERATION = "00000000-0000-0000-0000-000000000013"


class TestLoadTraceSearch(TraceEventsMixin, ClickhouseTestMixin, BaseTest):
    def test_counts_occurrences_per_event_across_content_and_names(self) -> None:
        bulk_create_ai_events(
            [
                self._event(
                    GENERATION,
                    event="$ai_generation",
                    properties={"$ai_input": [{"role": "user", "content": "Invoice total? The invoice is late."}]},
                ),
                self._event(
                    SPAN, properties={"$ai_span_name": "Fetch invoice", "$ai_output_state": {"note": "nothing here"}}
                ),
                self._event(QUIET_GENERATION, event="$ai_generation", properties={"$ai_model": "gpt-4o-mini"}),
            ]
        )

        loaded = load_trace_search(self.team, None, "trace-1", "INVOICE", None)

        assert loaded.counts == {GENERATION: 2, SPAN: 1}
        assert len(loaded.rows) == 3

    def test_trace_search_rows_carry_latency(self) -> None:
        bulk_create_ai_events(
            [
                self._event(GENERATION, event="$ai_generation", properties={"$ai_latency": 1.0, "$ai_model": "gpt-4o"}),
                self._event(QUIET_GENERATION, event="$ai_generation", properties={"$ai_latency": 2.0}),
            ]
        )

        loaded = load_trace_search(self.team, None, "trace-1", "gpt-4o", None)

        assert loaded.counts == {GENERATION: 1}
        assert {row.trace_latency_s for row in loaded.rows} == {3.0}

    @parameterized.expand(
        [
            ("a quoted phrase", '"late"', {"$ai_input": [{"content": 'It said "late" twice'}]}, 1),
            ("a backslash", "C:\\tmp", {"$ai_output": "saved to C:\\tmp"}, 1),
            ("a percent sign", "50%", {"$ai_output": "50% done, 500 left"}, 1),
            ("an underscore", "a_b", {"$ai_output": "a_b and axb"}, 1),
            ("an error object", "quota", {"$ai_error": {"message": "Quota exceeded"}}, 1),
            ("a quote after a trailing backslash", '"', {"$ai_output": "saved to C:\\"}, 0),
            ("backslashes before a quote", '\\"', {"$ai_output": 'C:\\\\"x" and \\\\'}, 1),
            (
                "non-ASCII text in a JSON string",
                "2 × 3",
                {"$ai_input": [{"arguments": json.dumps({"op": "2 × 3"})}]},
                1,
            ),
            ("quotes in a JSON string", '"', {"$ai_output": json.dumps('say "hi"')}, 4),
            ("a model", "GPT-4O", {"$ai_model": "gpt-4o-mini"}, 1),
            ("a provider", "anthropic", {"$ai_provider": "anthropic"}, 1),
            ("a trace name", "checkout", {"$ai_trace_name": "Checkout flow"}, 1),
        ]
    )
    def test_matches_text_as_stored_in_json(
        self, _name: str, query: str, properties: dict[str, object], expected: int
    ) -> None:
        self._ingest(NODE, properties, event="$ai_generation")

        assert load_trace_search(self.team, None, "trace-1", query, None).counts.get(NODE, 0) == expected


WINDOW = FallbackWindow(start=T0 - timedelta(hours=1), end=T0 + timedelta(days=1))
_EVENTS_TABLE = re.compile(r"FROM\s+(ai_events|events)")
# Ids with a double quote or a backslash read from a materialized column the test database lacks.
AWKWARD_TRACE_ID = "a,b'c/d #%"


def _uuid(index: int) -> str:
    return f"00000000-0000-0000-0000-{index:012d}"


@parameterized.expand([(1, 2000), (24, 2000), (25, 1999), (50, 999), (100, 499)])
def test_rows_per_trace_cap_fits_the_page_in_the_row_budget(trace_count: int, cap: int) -> None:
    assert rows_per_trace_cap(trace_count) == cap


def _page_uuids(loaded: dict[str, PageTraceRows]) -> dict[str, list[str]]:
    return {trace_id: sorted(row.uuid for row in page.rows) for trace_id, page in loaded.items()}


def _tables_read(queries: list[str]) -> list[str]:
    return [match[1] for query in queries if (match := _EVENTS_TABLE.search(query))]


class TestLoadTracesRows(TraceEventsMixin, ClickhouseTestMixin, BaseTest):
    def test_page_rows_come_back_grouped_by_trace(self) -> None:
        duplicated = self._event(_uuid(1), trace_id="first")
        bulk_create_ai_events(
            [
                duplicated,
                duplicated,
                self._event(_uuid(2), trace_id="first", event="$ai_generation", properties={"$ai_model": "gpt-6"}),
                self._event(_uuid(3), trace_id="second"),
            ]
        )

        loaded = load_traces_rows(self.team, self.user, ["first", "second"], WINDOW)

        assert _page_uuids(loaded) == {"first": [_uuid(1), _uuid(2)], "second": [_uuid(3)]}
        assert [row.model for row in loaded["first"].rows if row.uuid == _uuid(2)] == ["gpt-6"]
        assert not loaded["first"].truncated and not loaded["second"].truncated

    @parameterized.expand([("over the cap", 5, True), ("at the cap", 2, False)])
    def test_a_trace_over_the_cap_keeps_its_trace_event_and_is_marked(
        self, _name: str, spans: int, truncated: bool
    ) -> None:
        bulk_create_ai_events(
            [
                *(
                    self._event(_uuid(index), trace_id="big", timestamp=T0 + timedelta(seconds=index))
                    for index in range(spans)
                ),
                self._event(_uuid(99), trace_id="big", event="$ai_trace", timestamp=T0 + timedelta(minutes=5)),
            ]
        )

        with patch.object(trace_queries, "PAGE_ROW_CAP_PER_TRACE", 3):
            loaded = load_traces_rows(self.team, self.user, ["big"], WINDOW)["big"]

        assert loaded.truncated is truncated and len(loaded.rows) == 3
        assert sorted(row.uuid for row in loaded.rows) == [_uuid(0), _uuid(1), _uuid(99)]

    def test_every_trace_of_a_page_over_the_budget_keeps_its_cap_and_is_marked(self) -> None:
        trace_ids = ["first", "second", "third"]
        bulk_create_ai_events(
            [
                event
                for offset, trace_id in enumerate(trace_ids)
                for event in (
                    *(
                        self._event(
                            _uuid(offset * 10 + index), trace_id=trace_id, timestamp=T0 + timedelta(seconds=index)
                        )
                        for index in range(4)
                    ),
                    self._event(
                        _uuid(offset * 10 + 9),
                        trace_id=trace_id,
                        event="$ai_trace",
                        timestamp=T0 + timedelta(minutes=5),
                    ),
                )
            ]
        )

        with patch.object(trace_queries, "PAGE_ROW_BUDGET", 12):
            loaded = load_traces_rows(self.team, self.user, trace_ids, WINDOW)

        assert {
            trace_id: (len(page.rows), page.truncated, sum(row.event == "$ai_trace" for row in page.rows))
            for trace_id, page in loaded.items()
        } == dict.fromkeys(trace_ids, (3, True, 1))

    def test_page_rows_totals_cover_rows_past_the_cap(self) -> None:
        bulk_create_ai_events(
            [
                self._event(
                    _uuid(index),
                    trace_id="big",
                    event="$ai_generation",
                    timestamp=T0 + timedelta(seconds=index),
                    properties={
                        "$ai_latency": 2.0,
                        "$ai_total_cost_usd": 0.5,
                        **({"$ai_session_id": "session-1"} if index == 3 else {}),
                    },
                )
                for index in range(4)
            ]
        )

        with patch.object(trace_queries, "PAGE_ROW_CAP_PER_TRACE", 2):
            loaded = load_traces_rows(self.team, self.user, ["big"], WINDOW)["big"]

        assert loaded.truncated and len(loaded.rows) == 2
        assert {(row.trace_latency_s, row.trace_cost_usd, row.trace_session_id) for row in loaded.rows} == {
            (8.0, 2.0, "session-1")
        }

    def test_each_trace_of_a_page_carries_its_own_latency(self) -> None:
        bulk_create_ai_events(
            [
                self._event(_uuid(1), trace_id="fast", event="$ai_generation", properties={"$ai_latency": 1.0}),
                self._event(_uuid(2), trace_id="slow", event="$ai_generation", properties={"$ai_latency": 6.0}),
                self._event(_uuid(3), trace_id="slow", event="$ai_generation", properties={"$ai_latency": 2.0}),
            ]
        )

        loaded = load_traces_rows(self.team, self.user, ["fast", "slow"], WINDOW)

        assert {trace_id: {row.trace_latency_s for row in page.rows} for trace_id, page in loaded.items()} == {
            "fast": {1.0},
            "slow": {8.0},
        }

    @parameterized.expand([("on ai_events", bulk_create_ai_events), ("on the shared table", bulk_create_events)])
    def test_an_unknown_id_is_absent_and_awkward_ids_survive(
        self, _name: str, create_events: Callable[[list[dict[str, object]]], None]
    ) -> None:
        create_events([self._event(_uuid(1), trace_id=AWKWARD_TRACE_ID)])

        loaded = load_traces_rows(self.team, self.user, ["missing", AWKWARD_TRACE_ID], WINDOW)

        assert _page_uuids(loaded) == {AWKWARD_TRACE_ID: [_uuid(1)]}

    @parameterized.expand([("on ai_events", bulk_create_ai_events), ("on the shared table", bulk_create_events)])
    def test_another_teams_rows_never_load(
        self, _name: str, create_events: Callable[[list[dict[str, object]]], None]
    ) -> None:
        other_team = Team.objects.create(organization=self.organization)
        create_events([{**self._event(_uuid(1), trace_id="trace-1"), "team": other_team}])

        assert load_traces_rows(self.team, self.user, ["trace-1"], WINDOW) == {}

    def test_the_page_read_is_one_query_when_every_trace_is_on_ai_events(self) -> None:
        bulk_create_ai_events([self._event(_uuid(1), trace_id="first"), self._event(_uuid(2), trace_id="second")])

        with self.capture_select_queries() as queries:
            loaded = load_traces_rows(self.team, self.user, ["first", "second"], WINDOW)

        assert set(loaded) == {"first", "second"}
        assert len(queries) == 1

    def test_an_empty_page_runs_no_query(self) -> None:
        with self.capture_select_queries() as queries:
            loaded = load_traces_rows(self.team, self.user, [], WINDOW)

        assert loaded == {} and queries == []


class TestLoadPeople(ClickhouseTestMixin, BaseTest):
    @parameterized.expand(
        [
            ("email first", None, {"email": "ada@example.com", "name": "Ada", "username": "ada"}, "ada@example.com"),
            ("then name", None, {"name": "Ada", "username": "ada"}, "Ada"),
            ("then username", None, {"username": "ada"}, "ada"),
            ("then the distinct id", None, {"plan": "pro"}, "user-1"),
            (
                "the project's properties",
                ["nickname"],
                {"nickname": "Countess", "email": "ada@example.com"},
                "Countess",
            ),
            ("an empty property is skipped", None, {"email": "", "name": "Ada"}, "Ada"),
        ]
    )
    def test_a_person_is_labelled_by_the_projects_display_name_properties(
        self, _name: str, display_name_properties: list[str] | None, properties: dict[str, str], expected: str
    ) -> None:
        if display_name_properties is not None:
            self.team.person_display_name_properties = display_name_properties
            self.team.save()
        create_person(team=self.team, distinct_ids=["user-1"], properties=properties)

        [person] = load_people(self.team, self.user, ["user-1"]).values()

        assert person_label(person) == expected

    def test_a_display_name_key_with_quoting_characters_reads_only_that_property(self) -> None:
        self.team.person_display_name_properties = ["nick`name x"]
        self.team.save()
        create_person(team=self.team, distinct_ids=["named"], properties={"nick`name x": "Countess"})
        create_person(team=self.team, distinct_ids=["unnamed"], properties={"email": "ada@example.com"})

        people = load_people(self.team, self.user, ["named", "unnamed"])

        assert {distinct_id: person_label(person) for distinct_id, person in people.items()} == {
            "named": "Countess",
            "unnamed": "unnamed",
        }

    def test_every_requested_person_is_read_in_one_query(self) -> None:
        create_person(team=self.team, distinct_ids=["ada"], properties={"email": "ada@example.com"})
        create_person(team=self.team, distinct_ids=["grace"], properties={"email": "grace@example.com"})

        with self.capture_select_queries() as queries:
            people = load_people(self.team, self.user, ["ada", "grace"])

        assert people == {
            "ada": PersonRow(distinct_id="ada", display_name="ada@example.com"),
            "grace": PersonRow(distinct_id="grace", display_name="grace@example.com"),
        }
        assert len(queries) == 1

    def test_a_distinct_id_without_a_person_of_this_team_has_no_display_name(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        create_person(team=other_team, distinct_ids=["other-team"], properties={"email": "ada@example.com"})
        person = create_person(team=self.team, distinct_ids=["kept"], properties={"email": "grace@example.com"})
        add_distinct_id(person=person, distinct_id="removed")
        create_person_distinct_id(self.team.pk, "removed", str(person.uuid), version=1, is_deleted=True)
        deleted = create_person(team=self.team, distinct_ids=["deleted"], properties={"email": "joan@example.com"})
        delete_person(deleted)
        distinct_ids = ["unknown", "other-team", "removed", "deleted"]

        people = load_people(self.team, self.user, distinct_ids)

        assert people == {
            distinct_id: PersonRow(distinct_id=distinct_id, display_name=None) for distinct_id in distinct_ids
        }

    def test_a_moved_distinct_id_reads_the_person_it_moved_to(self) -> None:
        create_person(team=self.team, distinct_ids=["moved"], properties={"email": "first@example.com"})
        second = create_person(team=self.team, distinct_ids=["second"], properties={"email": "second@example.com"})
        add_distinct_id(person=second, distinct_id="moved", version=1)

        assert load_people(self.team, self.user, ["moved"]) == {
            "moved": PersonRow(distinct_id="moved", display_name="second@example.com")
        }


class TestLoadTraceDistinctIds(TraceEventsMixin, ClickhouseTestMixin, BaseTest):
    def test_a_trace_takes_its_trace_events_distinct_id_else_its_earliest_events(self) -> None:
        bulk_create_ai_events(
            [
                self._event(_uuid(1), trace_id="rooted", event="$ai_generation", distinct_id="generation-user"),
                self._event(
                    _uuid(2),
                    trace_id="rooted",
                    event="$ai_trace",
                    timestamp=T0 + timedelta(seconds=1),
                    distinct_id="root-user",
                ),
                self._event(_uuid(3), trace_id="rootless", timestamp=T0 + timedelta(seconds=2), distinct_id="late"),
                self._event(_uuid(4), trace_id="rootless", timestamp=T0 + timedelta(seconds=1), distinct_id="early"),
                self._event(
                    _uuid(5),
                    trace_id="rootless",
                    event="$ai_generation",
                    timestamp=T0 + timedelta(seconds=3),
                    distinct_id="generation-user",
                ),
            ]
        )

        distinct_ids = load_trace_distinct_ids(self.team, self.user, ["rooted", "rootless", "unknown"], WINDOW)

        assert distinct_ids == {"rooted": "root-user", "rootless": "early"}

    def test_a_trace_missing_from_ai_events_is_read_from_the_shared_table_inside_the_window(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        earlier = T0 - timedelta(seconds=1)
        bulk_create_ai_events(
            [
                self._event(_uuid(1), trace_id="recent", distinct_id="recent-user"),
                {
                    **self._event(_uuid(2), trace_id="recent", timestamp=earlier, distinct_id="other"),
                    "team": other_team,
                },
            ]
        )
        bulk_create_events(
            [
                self._event(_uuid(3), trace_id="aged", distinct_id="aged-user"),
                self._event(
                    _uuid(4), trace_id="outside", timestamp=WINDOW.end + timedelta(minutes=1), distinct_id="outside"
                ),
                {**self._event(_uuid(5), trace_id="aged", timestamp=earlier, distinct_id="other"), "team": other_team},
            ]
        )

        distinct_ids = load_trace_distinct_ids(self.team, self.user, ["recent", "aged", "outside"], WINDOW)

        assert distinct_ids == {"recent": "recent-user", "aged": "aged-user"}
