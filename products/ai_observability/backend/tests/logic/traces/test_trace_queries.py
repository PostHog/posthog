import json
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_person
from unittest.mock import patch

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.models import Team
from posthog.models.ai_events.sql import AI_EVENTS_MV_SQL
from posthog.models.ai_events.test_util import bulk_create_ai_events
from posthog.models.event.util import bulk_create_events

from products.ai_observability.backend.logic.traces import trace_queries
from products.ai_observability.backend.logic.traces.trace_queries import (
    GitStampRow,
    SearchNeedles,
    TraceRootLookup,
    is_truthy_json,
    load_trace,
    load_trace_feedback_rows,
    load_trace_git_rows,
    load_trace_node,
    load_trace_root,
    load_trace_search,
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

    def test_ingested_values_read_like_the_legacy_view(self) -> None:
        self._ingest(
            "00000000-0000-0000-0000-000000000001",
            {"$ai_error": "", "$ai_input_tokens": {"total": 7}, "$ai_git_branch": ""},
        )
        self._ingest(
            "00000000-0000-0000-0000-000000000002",
            {
                "$ai_error": {"message": "boom"},
                "$ai_input_tokens": 3,
                "$ai_git_branch": "feat/rag",
                "$ai_git_repo": "acme/app",
            },
        )

        rows = load_trace(self.team, None, "trace-1", None).rows

        assert sorted(
            (row.uuid, row.error_is_truthy, row.input_tokens, row.git_branch, row.git_repo) for row in rows
        ) == [
            ("00000000-0000-0000-0000-000000000001", False, 7, None, None),
            ("00000000-0000-0000-0000-000000000002", True, 3, "feat/rag", "acme/app"),
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
        clean_span: dict[str, object] = {"$ai_error": "", "$ai_input_tokens": {"total": 7}}
        bulk_create_events(
            [
                self._event("00000000-0000-0000-0000-000000000001", properties=old_span),
                self._event("00000000-0000-0000-0000-000000000002", properties=clean_span),
            ]
        )

        loaded = load_trace(self.team, None, "trace-1", timestamp_hint)

        assert sorted(
            (row.uuid, row.span_name, row.error_is_truthy, row.input_tokens, row.git_branch) for row in loaded.rows
        ) == [
            ("00000000-0000-0000-0000-000000000001", "old", True, None, "feat/rag"),
            ("00000000-0000-0000-0000-000000000002", None, False, 7, None),
        ]

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
