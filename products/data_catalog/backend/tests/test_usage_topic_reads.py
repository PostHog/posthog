import json
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.test import SimpleTestCase

from parameterized import parameterized

from products.data_catalog.backend.logic.agent_sessions import SessionText
from products.data_catalog.backend.logic.usage_topic_reads import (
    READ_CHARS,
    ReadCall,
    ReadSources,
    SavedDefinition,
    session_tables,
    topic_tables,
    trace_session_tables,
)
from products.product_analytics.backend.facade.models import Insight

_CALL_AT = datetime(2026, 10, 10, tzinfo=UTC)


def _call(tool: str, payload: Any = None, *, sql: str = "", event: str = "$ai_span", cut: bool = False) -> ReadCall:
    return ReadCall(session="s1", tool=tool, event=event, at=_CALL_AT, payload=payload, sql=sql, cut=cut)


def _sql(sql: str) -> ReadCall:
    return _call("execute-sql", sql=sql, event="$ai_generation")


def _trends(*nodes: dict[str, Any], properties: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"kind": "TrendsQuery", "series": list(nodes), "properties": properties or []}


_EVENTS_NODE = {"kind": "EventsNode", "event": "$pageview"}
_WAREHOUSE_NODE = {"kind": "DataWarehouseNode", "table_name": "stripe_charges", "math_hogql": None}
_HOGQL_INSIGHT = {"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": "SELECT 1 FROM billing"}}
_HOGQL_FILTER = {"type": "hogql", "key": "[redacted]"}


def _saved(body: Any, changed_at: datetime = _CALL_AT - timedelta(days=1)) -> SavedDefinition:
    return SavedDefinition(body=body, changed_at=changed_at)


_EDITED = _CALL_AT + timedelta(days=1)
_SOURCES = ReadSources(
    metric_definitions={
        "mrr": _saved({"kind": "HogQLQuery", "query": "SELECT sum(amount) FROM billing"}),
        "steps": _saved({"kind": "MarkdownDefinition", "markdown": "Run a query."}),
        "edited": _saved(_trends(_EVENTS_NODE), _EDITED),
    },
    insight_queries={"abc123": _saved(_HOGQL_INSIGHT), "edited": _saved(_trends(_EVENTS_NODE), _EDITED)},
)


class TestSessionTables(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "sql_names_its_tables",
                [_sql("SELECT a.x FROM billing a JOIN plans p ON a.p = p.id")],
                {"billing", "plans"},
            ),
            (
                "metadata_search_reads_its_query_from_the_input",
                [_call("execute-sql", {"query": "SELECT 1 FROM system.information_schema.tables"})],
                {"system.information_schema.tables"},
            ),
            ("unparseable_sql", [_sql("SELECT count( FROM billing")], None),
            ("cut_call", [_call("execute-sql", sql="SELECT 1 FROM events", event="$ai_generation", cut=True)], None),
            ("typed_query_over_events", [_call("query-trends", _trends(_EVENTS_NODE))], set()),
            (
                "typed_query_over_a_warehouse_table",
                [_call("query-trends", _trends(_WAREHOUSE_NODE))],
                {"stripe_charges"},
            ),
            (
                "typed_query_with_a_hogql_filter",
                [_call("query-trends", _trends(_EVENTS_NODE, properties=[_HOGQL_FILTER]))],
                None,
            ),
            (
                "typed_query_with_a_warehouse_person_property",
                [_call("query-trends", _trends(_EVENTS_NODE, properties=[{"type": "data_warehouse_person_property"}]))],
                None,
            ),
            (
                "funnel_over_a_warehouse_table",
                [
                    _call(
                        "query-funnel",
                        {
                            "kind": "FunnelsQuery",
                            "series": [{"kind": "FunnelsDataWarehouseNode", "table_name": "stripe_charges"}],
                        },
                    )
                ],
                {"stripe_charges"},
            ),
            ("query_over_an_action", [_call("query-trends", _trends({"kind": "ActionsNode", "id": 1}))], None),
            ("cut_typed_input", [_call("query-trends", '{"kind": "TrendsQuery", "ser')], None),
            ("hogql_metric_run", [_call("data-catalog-metric-run", {"name": "mrr"})], {"billing"}),
            ("markdown_metric_run", [_call("data-catalog-metric-run", {"name": "steps"})], set()),
            ("run_of_a_metric_the_scan_cannot_find", [_call("data-catalog-metric-run", {"name": "gone"})], None),
            ("saved_insight_run", [_call("insight-query", {"insightId": "abc123"})], {"billing"}),
            (
                "insight_run_with_a_date_override",
                [_call("insight-query", {"insightId": "abc123", "filters_override": {"date_from": "-7d"}})],
                {"billing"},
            ),
            (
                "insight_run_with_a_hogql_filter_override",
                [_call("insight-query", {"insightId": "abc123", "filters_override": {"properties": [_HOGQL_FILTER]}})],
                None,
            ),
            ("insight_edited_after_the_run", [_call("insight-query", {"insightId": "edited"})], None),
            ("metric_edited_after_the_run", [_call("data-catalog-metric-run", {"name": "edited"})], None),
            ("run_of_an_insight_the_scan_cannot_find", [_call("insight-query", {"insightId": "gone"})], None),
            ("dashboard_run", [_call("dashboard-insights-run", {"id": 1})], None),
        ]
    )
    def test_traces_each_call_and_fails_closed(
        self, _name: str, calls: list[ReadCall], expected: set[str] | None
    ) -> None:
        tools = {call.tool for call in calls}

        found = session_tables(calls, tools, _SOURCES)

        assert found == (None if expected is None else frozenset(expected))

    def test_a_data_tool_with_no_call_found_makes_the_session_unknown(self) -> None:
        assert session_tables([_sql("SELECT 1 FROM billing")], {"execute-sql", "query-trends"}, _SOURCES) is None

    def test_one_unknown_session_makes_the_topic_unknown(self) -> None:
        tables = {"a": frozenset({"billing"}), "b": frozenset({"plans"}), "c": None}

        assert topic_tables(["a", "b"], tables) == ["billing", "plans"]
        assert topic_tables(["a", "c"], tables) is None
        assert topic_tables(["a", "missing"], tables) is None


class TestTraceSessionTables(ClickhouseTestMixin, BaseTest):
    def _span(self, piece: str, at: datetime, tool: str, event: str, **properties: Any) -> None:
        _create_event(
            team=self.team,
            event=event,
            distinct_id="d1",
            timestamp=at,
            properties={
                "$session_id": piece,
                "$mcp_project_uuid": str(self.team.uuid),
                "$ai_trace_id": f"t-{piece}",
                "$ai_span_name": tool,
                **properties,
            },
        )

    def test_a_conversation_reads_what_its_pieces_read(self) -> None:
        end = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
        at = end - timedelta(hours=3)
        Insight.objects.create(
            team=self.team, short_id="abc123", query=_HOGQL_INSIGHT, last_modified_at=at - timedelta(days=1)
        )
        self._span(
            "p1",
            at,
            "execute-sql",
            "$ai_generation",
            **{"$ai_output_choices": [{"role": "assistant", "content": "SELECT 1 FROM plans"}]},
        )
        self._span("p2", at, "query-trends", "$ai_span", **{"$ai_input_state": json.dumps(_trends(_WAREHOUSE_NODE))})
        self._span("p2", at, "insight-query", "$ai_span", **{"$ai_input_state": json.dumps({"insightId": "abc123"})})
        self._span(
            "p3",
            at,
            "execute-sql",
            "$ai_generation",
            **{"$ai_output_choices": [{"role": "assistant", "content": "SELECT 1 FROM t WHERE " + "x" * READ_CHARS}]},
        )
        flush_persons_and_events()
        sessions = [
            SessionText(
                session_id="c1",
                person="p",
                notes=("q",),
                tools=frozenset({"execute-sql", "query-trends", "insight-query"}),
            ),
            SessionText(session_id="p3", person="p", notes=("q",), tools=frozenset({"execute-sql"})),
        ]

        tables = trace_session_tables(
            team=self.team,
            telemetry_team=self.team,
            window_start=end - timedelta(days=1),
            window_end=end,
            sessions=sessions,
            members={"c1": ("p1", "p2")},
        )

        assert tables == {"c1": frozenset({"plans", "stripe_charges", "billing"}), "p3": None}
