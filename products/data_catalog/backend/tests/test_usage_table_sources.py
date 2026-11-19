import json
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.data_catalog.backend.facade.contracts import TableSource
from products.data_catalog.backend.logic.usage_table_sources import (
    SessionQuery,
    TableSearch,
    build_table_sources,
    fetch_table_sources,
    reads_table,
    tables_in_search,
)

AT = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


class TestTableSources(SimpleTestCase):
    @parameterized.expand(
        [
            ("table_column", "", "table_name|description\nrevenue|Money\nusers|People", {"revenue", "users"}),
            ("name_column", "", "name|description\nrevenue|Money", {"revenue"}),
            ("skips_a_warning_first", "", "[Sync warnings]\n- Sync of x\ntable_name|d\nrevenue|Money", {"revenue"}),
            ("header_only_finds_nothing", "", "table_name|description", set()),
            (
                "column_search_names_the_table_in_its_filter",
                "SELECT column_name, description FROM c WHERE table_name = 'revenue'",
                "column_name|description\nid|Identifier",
                {"revenue"},
            ),
            ("drops_text_that_is_not_a_name", "", "table_name|d\nnot a name|x\nrevenue|y", {"revenue"}),
            (
                "skips_rows_without_a_description",
                "",
                "table_name|description\nrevenue|Money\nblank| \nnulled|null\nnoned|None",
                {"revenue"},
            ),
            (
                "column_search_without_descriptions_finds_nothing",
                "SELECT column_name, description FROM c WHERE table_name = 'revenue'",
                "column_name|description\nid|null",
                set(),
            ),
        ]
    )
    def test_tables_in_search(self, _name: str, query: str, result: str, expected: set[str]) -> None:
        assert tables_in_search(query, result) == frozenset(expected)

    @parameterized.expand(
        [
            ("from", "SELECT 1 FROM revenue", "revenue", True),
            ("join_with_a_schema", "SELECT 1 FROM a JOIN prod.revenue ON 1", "postgres.prod.revenue", True),
            ("only_a_column_name", "SELECT revenue FROM a", "revenue", False),
            ("longer_table_name", "SELECT 1 FROM revenue_daily", "revenue", False),
            ("same_last_part_in_another_schema", "SELECT 1 FROM stripe.customers", "hubspot.customers", False),
            ("unqualified_read", "SELECT 1 FROM customers", "stripe.customers", True),
            ("quoted_parts", 'SELECT 1 FROM "prod"."Revenue"', "prod.revenue", True),
        ]
    )
    def test_reads_table(self, _name: str, sql: str, table: str, expected: bool) -> None:
        assert reads_table(sql, table) is expected

    def test_a_table_counts_when_a_later_query_reads_it_and_posthog_tables_stay_out(self) -> None:
        searches = [
            TableSearch(session_id="a", person="p1", occurred_at=AT, tables=frozenset({"wide", "unused", "system.x"})),
            TableSearch(session_id="b", person="p2", occurred_at=AT, tables=frozenset({"wide"})),
            TableSearch(session_id="c", person="p1", occurred_at=AT, tables=frozenset({"busy"})),
            TableSearch(session_id="d", person="p1", occurred_at=AT, tables=frozenset({"busy"})),
            TableSearch(session_id="e", person="p3", occurred_at=AT, tables=frozenset({"earlier"})),
        ]
        later = AT + timedelta(minutes=1)
        queries = [
            SessionQuery(session_id="a", occurred_at=later, sql="SELECT 1 FROM wide JOIN unused JOIN system.x"),
            SessionQuery(session_id="b", occurred_at=later, sql="SELECT 1 FROM wide"),
            SessionQuery(session_id="c", occurred_at=later, sql="SELECT 1 FROM busy"),
            SessionQuery(session_id="d", occurred_at=later, sql="SELECT 1 FROM busy"),
            SessionQuery(session_id="other", occurred_at=later, sql="SELECT 1 FROM unused"),
            SessionQuery(session_id="e", occurred_at=AT - timedelta(minutes=1), sql="SELECT 1 FROM earlier"),
        ]

        assert build_table_sources(searches, queries, native_tables={"unused"}) == [
            TableSource(name="wide", sessions=2, people=2),
            TableSource(name="busy", sessions=2, people=1),
        ]


class TestFetchTableSources(ClickhouseTestMixin, BaseTest):
    def _span(self, source: str, trace: str, session: str, query: str, result: str) -> None:
        _create_event(
            team=self.team,
            event="$ai_span",
            distinct_id="d1",
            timestamp=AT - timedelta(hours=3),
            properties={
                "$session_id": session,
                "$mcp_project_uuid": str(self.team.uuid),
                "$ai_trace_id": trace,
                "$ai_span_name": "execute-sql",
                "$ai_input_state": json.dumps({"query": query}),
                "$ai_output_state": result,
                "source": source,
            },
        )

    def _query(self, source: str, trace: str, session: str, sql: str) -> None:
        _create_event(
            team=self.team,
            event="$ai_generation",
            distinct_id="d1",
            timestamp=AT - timedelta(hours=2),
            properties={
                "$session_id": session,
                "$mcp_project_uuid": str(self.team.uuid),
                "$ai_trace_id": trace,
                "$ai_span_name": "execute-sql",
                "$ai_output_choices": [{"role": "assistant", "content": sql}],
                "source": source,
            },
        )

    def test_reads_searches_and_later_queries_and_leaves_out_scouts(self) -> None:
        search = "SELECT table_name, description FROM system.information_schema.tables"
        no_descriptions = "SELECT table_name FROM system.information_schema.tables"
        self._span("mcp", "t1", "person", search, "table_name|description\nrevenue|Money\nevents|Every event")
        self._query("mcp", "t1", "person", "SELECT 1 FROM revenue JOIN events")
        self._span("self_driving", "t2", "scout", search, "table_name|description\nscout_table|Money")
        self._query("self_driving", "t2", "scout", "SELECT 1 FROM scout_table")
        self._span("mcp", "t3", "names_only", no_descriptions, "table_name|x\nnames_table|y")
        self._query("mcp", "t3", "names_only", "SELECT 1 FROM names_table")
        # One conversation recorded as two sessions: the search in one, the query in the other.
        self._span("mcp", "t4", "piece_one", search, "table_name|description\norders|Every order")
        self._query("mcp", "t5", "piece_two", "SELECT 1 FROM orders")
        flush_persons_and_events()

        # A batch of one piece still keeps both pieces of one conversation together.
        with patch("products.data_catalog.backend.logic.usage_table_sources._SESSION_BATCH", 1):
            sources = fetch_table_sources(
                team=self.team,
                telemetry_team=self.team,
                window_start=AT - timedelta(days=1),
                window_end=AT,
                units={"piece_one": "piece_one", "piece_two": "piece_one"},
            )

        assert sorted(sources, key=lambda source: source.name) == [
            TableSource(name="orders", sessions=1, people=1),
            TableSource(name="revenue", sessions=1, people=1),
        ]
