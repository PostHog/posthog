import json
import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin, NonAtomicBaseTest, _create_event, flush_persons_and_events

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog

from products.cohorts.backend.models.cohort import Cohort
from products.data_catalog.backend.logic.agent_sessions import SessionText
from products.data_catalog.backend.logic.usage_topic_reads import (
    READ_CHARS,
    CohortDefinition,
    ReadCall,
    ReadSources,
    SavedDefinition,
    SavedFilters,
    SavedView,
    call_tables,
    cohort_reads,
    fetch_cohorts,
    load_read_sources,
    saved_field_tables,
    session_tables,
    topic_tables,
    trace_session_tables,
    view_changes,
    view_field_reads,
)
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_tools.backend.facade.models import DataWarehouseExpression, DataWarehouseJoin
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
    saved_filters=SavedFilters(cohorts={7: True, 8: False}, test_account_tables=frozenset()),
    field_tables={
        "stripe": frozenset({"stripe_customers"}),
        "billing_total": frozenset({"events", "billing"}),
        "broken_total": None,
        "$billing_total": frozenset({"events", "billing"}),
    },
    table_expressions={"events": frozenset({"billing_total"})},
    view_changes={"revenue_view": _EDITED, "stable_view": _CALL_AT - timedelta(days=1)},
    view_reads={"cohort_view": None, "stable_view": frozenset(), "wide_view": frozenset({"billing"})},
)


def _in_cohort(cohort_id: int) -> dict[str, Any]:
    return {"type": "cohort", "key": "id", "value": cohort_id}


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
            (
                "sql_through_a_warehouse_join",
                [_sql("SELECT person.stripe.email FROM events")],
                {"events", "stripe_customers"},
            ),
            ("sql_using_a_saved_expression", [_sql("SELECT billing_total FROM events")], {"events", "billing"}),
            ("sql_using_an_untraceable_saved_expression", [_sql("SELECT broken_total FROM events")], None),
            ("sql_using_a_dollar_saved_expression", [_sql("SELECT $billing_total FROM events")], {"events", "billing"}),
            ("sql_selecting_every_field", [_sql("SELECT * FROM events")], {"events", "billing"}),
            ("sql_with_a_query_tag", [_sql("SELECT 1 FROM <HogQLQuery query='SELECT 1 FROM billing' />")], None),
            ("sql_with_a_filters_placeholder", [_sql("SELECT 1 FROM events WHERE {filters}")], None),
            (
                "sql_with_a_bound_filters_placeholder",
                [_sql("SELECT 1 FROM events WHERE {filters(timestamp AS timestamp)}")],
                None,
            ),
            ("typed_query_with_no_kind", [_call("query-trends", {"series": [_EVENTS_NODE]})], None),
            (
                "sql_over_a_view_by_its_models_name",
                [_sql("SELECT 1 FROM models.wide_view")],
                {"models.wide_view", "wide_view", "billing"},
            ),
            (
                "sql_selecting_every_field_by_the_full_table_name",
                [_sql("SELECT * FROM posthog.events")],
                {"posthog.events", "events", "billing"},
            ),
            ("sql_selecting_fields_by_pattern", [_sql("SELECT COLUMNS('bill.*') FROM events")], {"events", "billing"}),
            ("sql_counting_rows_reads_no_field", [_sql("SELECT count(*) FROM events")], {"events"}),
            ("sql_over_a_view_the_scan_cannot_trace", [_sql("SELECT 1 FROM cohort_view")], None),
            ("sql_over_a_view_that_reads_through_a_field", [_sql("SELECT 1 FROM wide_view")], {"wide_view", "billing"}),
            ("sql_over_a_view_edited_after_the_run", [_sql("SELECT 1 FROM revenue_view")], None),
            ("sql_over_a_view_edited_before_the_run", [_sql("SELECT 1 FROM stable_view")], {"stable_view"}),
            (
                "query_kind_the_scan_does_not_trace",
                [_call("query-marketing-recommendations", {"kind": "MarketingAnalyticsRecommendationsQuery"})],
                None,
            ),
            ("sql_in_a_cohort", [_sql("SELECT count() FROM events WHERE person_id IN COHORT 7")], None),
            ("sql_matching_an_action", [_sql("SELECT count() FROM events WHERE matchesAction('Signed up')")], None),
            (
                "sql_in_a_cohort_behind_a_comment",
                [_sql("SELECT count() FROM events WHERE person_id IN /* c */ COHORT 7")],
                None,
            ),
            (
                "warehouse_person_property_as_a_math_property",
                [
                    _call(
                        "query-trends",
                        _trends(
                            {
                                **_EVENTS_NODE,
                                "math": "sum",
                                "math_property": "revenue",
                                "math_property_type": "data_warehouse_person_properties",
                            }
                        ),
                    )
                ],
                None,
            ),
            (
                "cohort_over_posthog_tables",
                [_call("query-trends", _trends(_EVENTS_NODE, properties=[_in_cohort(7)]))],
                set(),
            ),
            (
                "cohort_that_can_read_any_table",
                [_call("query-trends", _trends(_EVENTS_NODE, properties=[_in_cohort(8)]))],
                None,
            ),
            (
                "cohort_the_scan_cannot_find",
                [_call("query-trends", _trends(_EVENTS_NODE, properties=[_in_cohort(9)]))],
                None,
            ),
            (
                "cohort_breakdown",
                [
                    _call(
                        "query-trends",
                        {
                            **_trends(_EVENTS_NODE),
                            "breakdownFilter": {"breakdown_type": "cohort", "breakdown": [8, "all"]},
                        },
                    )
                ],
                None,
            ),
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

    @parameterized.expand(
        [
            ("a_data_tool_with_no_read_logged", {"execute-sql", "query-trends"}, {}, None),
            ("a_call_whose_read_the_server_left_out", {"execute-sql"}, {"execute-sql": 2}, None),
            ("a_metadata_search_logs_twice_for_one_call", {"execute-sql"}, {"execute-sql": 1}, {"billing"}),
        ]
    )
    def test_fewer_logged_reads_than_calls_makes_the_session_unknown(
        self, _name: str, tools: set[str], call_counts: dict[str, int], expected: set[str] | None
    ) -> None:
        sql = "SELECT 1 FROM billing"
        calls = [_sql(sql), _call("execute-sql", {"query": sql})]

        found = session_tables(calls, tools, _SOURCES, call_counts)

        assert found == (None if expected is None else frozenset(expected))

    def test_a_cohort_reads_only_posthog_tables_unless_its_filters_can_read_any_table(self) -> None:
        def cohort(
            cohort_id: int, *values: dict[str, Any], is_static: bool = False, query: Any = None
        ) -> CohortDefinition:
            filters = {"properties": {"type": "AND", "values": list(values)}}
            return CohortDefinition(id=cohort_id, is_static=is_static, filters=filters, query=query)

        person = {"type": "person", "key": "email", "value": "a@example.com"}
        cohorts = [
            cohort(1, _HOGQL_FILTER, is_static=True),
            cohort(2, person),
            cohort(3, person, query={"kind": "HogQLQuery", "query": "SELECT 1"}),
            cohort(4, {"type": "behavioral", "value": "performed_event", "event_filters": [_HOGQL_FILTER]}),
            cohort(5, {"type": "behavioral", "value": "performed_event", "event_type": "actions", "key": 3}),
            cohort(6, _in_cohort(2)),
            cohort(7, _in_cohort(3)),
            cohort(8, _in_cohort(9)),
            cohort(9, _in_cohort(8)),
            cohort(10, _in_cohort(99)),
        ]

        reads = cohort_reads({definition.id: definition for definition in cohorts})

        assert {cohort_id for cohort_id, only_posthog in reads.items() if only_posthog} == {1, 2, 6}

    @parameterized.expand(
        [
            (
                "a_cohort",
                dataclasses.replace(
                    _SOURCES, saved_filters=dataclasses.replace(_SOURCES.saved_filters, cohort_changes={7: _EDITED})
                ),
                _trends(_EVENTS_NODE, properties=[_in_cohort(7)]),
            ),
            (
                "the_test_account_filters",
                dataclasses.replace(
                    _SOURCES,
                    saved_filters=dataclasses.replace(_SOURCES.saved_filters, test_accounts_changed_at=_EDITED),
                ),
                {**_trends(_EVENTS_NODE), "filterTestAccounts": True},
            ),
            ("a_join_or_expression", dataclasses.replace(_SOURCES, fields_changed_at=_EDITED), _trends(_EVENTS_NODE)),
        ]
    )
    def test_a_saved_filter_that_changed_after_the_call_makes_the_call_unknown(
        self, _name: str, changed: ReadSources, query: dict[str, Any]
    ) -> None:
        call = _call("query-trends", query)

        assert session_tables([call], {"query-trends"}, _SOURCES) is not None
        assert session_tables([call], {"query-trends"}, changed) is None

    @parameterized.expand(
        [
            ("set", {"filterTestAccounts": True}, {"crm_users"}),
            ("omitted_so_the_project_default_can_set_it", {}, {"crm_users"}),
            ("turned_off", {"filterTestAccounts": False}, set()),
        ]
    )
    def test_a_typed_query_reads_what_the_test_account_filters_read(
        self, _name: str, flag: dict[str, bool], expected: set[str]
    ) -> None:
        sources = dataclasses.replace(
            _SOURCES,
            saved_filters=dataclasses.replace(_SOURCES.saved_filters, test_account_tables=frozenset({"crm_users"})),
        )
        call = _call("query-trends", {**_trends(_EVENTS_NODE), **flag})

        assert session_tables([call], {"query-trends"}, sources) == frozenset(expected)

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

    def _tool_call(self, piece: str, at: datetime, tool: str) -> None:
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id="d1",
            timestamp=at,
            properties={"$session_id": piece, "$mcp_project_uuid": str(self.team.uuid), "$mcp_tool_name": tool},
        )

    def test_a_conversation_reads_what_its_pieces_read(self) -> None:
        end = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
        at = end - timedelta(hours=3)
        Insight.objects.create(
            team=self.team, short_id="abc123", query=_HOGQL_INSIGHT, last_modified_at=at - timedelta(days=1)
        )
        self.team.test_account_filters = [{"type": "person", "key": "email", "value": "x", "operator": "not_icontains"}]
        self.team.save()
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="events",
            source_table_key="distinct_id",
            joining_table_name="stripe_customers",
            joining_table_key="id",
            field_name="stripe",
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
        test_accounts_query = {**_trends(_EVENTS_NODE, properties=[{"type": "event", "key": "stripe.plan"}])}
        self._span(
            "p4",
            at,
            "query-trends",
            "$ai_span",
            **{"$ai_input_state": json.dumps({**test_accounts_query, "filterTestAccounts": True})},
        )
        self._tool_call("p4", at, "query-trends")
        self._span(
            "p5",
            at,
            "execute-sql",
            "$ai_generation",
            **{"$ai_output_choices": [{"role": "assistant", "content": "SELECT 1 FROM plans"}]},
        )
        self._tool_call("p5", at, "execute-sql")
        self._tool_call("p5", at + timedelta(minutes=1), "execute-sql")
        flush_persons_and_events()
        sessions = [
            SessionText(
                session_id="c1",
                person="p",
                notes=("q",),
                tools=frozenset({"execute-sql", "query-trends", "insight-query"}),
            ),
            SessionText(session_id="p3", person="p", notes=("q",), tools=frozenset({"execute-sql"})),
            SessionText(session_id="p4", person="p", notes=("q",), tools=frozenset({"query-trends"})),
            SessionText(session_id="p5", person="p", notes=("q",), tools=frozenset({"execute-sql"})),
        ]

        tables = trace_session_tables(
            team=self.team,
            telemetry_team=self.team,
            window_start=end - timedelta(days=1),
            window_end=end,
            sessions=sessions,
            members={"c1": ("p1", "p2")},
        )

        assert tables == {
            "c1": frozenset({"plans", "stripe_charges", "billing"}),
            "p3": None,
            "p4": frozenset({"stripe_customers"}),
            "p5": None,
        }


class TestViewChanges(SimpleTestCase):
    def test_a_view_changes_when_it_or_a_view_that_it_reads_changes(self) -> None:
        def at(day: int) -> datetime:
            return datetime(2026, 10, day, tzinfo=UTC)

        views = [
            SavedView(names=frozenset({"base"}), sql="SELECT 1 FROM billing", changed_at=at(9)),
            SavedView(names=frozenset({"top"}), sql="SELECT 1 FROM models.base", changed_at=at(2)),
            SavedView(names=frozenset({"POSTHOG_DELETED_1", "gone"}), sql="SELECT 1 FROM events", changed_at=at(5)),
            SavedView(names=frozenset({"ping"}), sql="SELECT 1 FROM pong", changed_at=at(3)),
            SavedView(names=frozenset({"pong"}), sql="SELECT 1 FROM ping", changed_at=at(4)),
            SavedView(
                names=frozenset({"in_cohort"}), sql="SELECT 1 FROM events WHERE person_id IN COHORT 7", changed_at=at(1)
            ),
            SavedView(names=frozenset({"over_in_cohort"}), sql="SELECT 1 FROM in_cohort", changed_at=at(1)),
            SavedView(names=frozenset({"wide"}), sql="SELECT * FROM events", changed_at=at(1)),
            SavedView(names=frozenset({"over_wide"}), sql="SELECT person.stripe.email FROM wide", changed_at=at(1)),
        ]

        changes = view_changes(views)

        assert changes["top"] == at(9)
        assert changes["gone"] == at(5)
        assert changes["ping"] == changes["pong"] == at(4)
        assert view_field_reads(views, _SOURCES) == {
            "base": frozenset({"billing"}),
            "top": frozenset({"models.base", "base", "billing"}),
            "POSTHOG_DELETED_1": frozenset({"events"}),
            "gone": frozenset({"events"}),
            "ping": None,
            "pong": None,
            "in_cohort": None,
            "over_in_cohort": None,
            "wide": frozenset({"events", "billing"}),
            "over_wide": frozenset({"wide", "events", "billing", "stripe_customers"}),
        }


class TestSavedFieldTables(SimpleTestCase):
    def test_an_expression_reads_its_body_and_the_fields_it_uses(self) -> None:
        joins = {"stripe": {"stripe_customers"}}
        expressions = {
            "billing_total": {("events", "(SELECT sum(amount) FROM billing)")},
            "billing_double": {("events", "billing_total * 2")},
            "plan": {("events", "stripe.plan")},
            "broken": {("events", "sum(")},
            "ping": {("events", "pong + 1")},
            "pong": {("events", "ping + 1")},
        }

        tables = saved_field_tables(joins, expressions)

        assert tables == {
            "stripe": frozenset({"stripe_customers"}),
            "billing_total": frozenset({"events", "billing"}),
            "billing_double": frozenset({"events", "billing"}),
            "plan": frozenset({"events", "stripe_customers"}),
            "broken": None,
            "ping": None,
            "pong": None,
        }


class TestLoadReadSources(BaseTest):
    def _log(self, scope: str, item_id: str, at: datetime, field: str = "") -> None:
        changes = [{"type": scope, "action": "changed", "field": field}] if field else []
        entry = ActivityLog.objects.create(
            team_id=self.team.id, scope=scope, item_id=item_id, activity="updated", detail={"changes": changes}
        )
        ActivityLog.objects.filter(id=entry.id).update(created_at=at)

    def test_a_call_before_a_change_of_a_join_or_the_test_account_filters_is_unknown(self) -> None:
        start = datetime(2026, 10, 1, tzinfo=UTC)
        self.team.test_account_filters = [{"type": "person", "key": "email", "value": "x", "operator": "not_icontains"}]
        self.team.save()
        self._log("DataWarehouseJoin", "a-join", start + timedelta(days=1))
        self._log("Team", str(self.team.id), start + timedelta(days=3), field="test_account_filters")
        self._log("Team", str(self.team.id), start + timedelta(days=5), field="name")
        query = {**_trends(_EVENTS_NODE), "filterTestAccounts": True}
        calls = [
            ReadCall(
                session="s1",
                tool="query-trends",
                event="$ai_span",
                at=start + timedelta(days=day),
                payload=query,
                sql="",
                cut=False,
            )
            for day in (0, 2, 4)
        ]

        sources = load_read_sources(self.team, calls, start)

        assert [call_tables(call, sources) for call in calls] == [None, None, frozenset()]

    def test_a_call_over_a_view_that_changed_after_the_call_is_unknown(self) -> None:
        view = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="revenue_view", query={"kind": "HogQLQuery", "query": "SELECT 1 FROM events"}
        )
        DataWarehouseSavedQuery.objects.filter(id=view.id).update(
            created_at=_CALL_AT - timedelta(days=2), query_updated_at=_CALL_AT + timedelta(days=1)
        )
        call = _sql("SELECT 1 FROM revenue_view")

        sources = load_read_sources(self.team, [call], _CALL_AT - timedelta(days=3))

        assert call_tables(call, sources) is None

    def test_a_call_over_a_name_that_no_table_has_after_a_view_save_is_unknown(self) -> None:
        DataWarehouseSavedQuery.objects.create(
            team=self.team, name="new_name", query={"kind": "HogQLQuery", "query": "SELECT 1 FROM events"}
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team, name="over_old_name", query={"kind": "HogQLQuery", "query": "SELECT 1 FROM old_name"}
        )
        DataWarehouseSavedQuery.objects.filter(team=self.team).update(
            created_at=_CALL_AT - timedelta(days=2), updated_at=_CALL_AT + timedelta(days=1)
        )
        DataWarehouseExpression.objects.for_team(self.team.id).create(
            team=self.team, table_name="events", field_name="old_total", expression="(SELECT count() FROM old_name)"
        )
        calls = [
            _sql("SELECT 1 FROM old_name"),
            _sql("SELECT old_total FROM events"),
            _sql("SELECT 1 FROM over_old_name"),
            _sql("SELECT 1 FROM new_name"),
            _sql("SELECT 1 FROM events"),
        ]

        sources = load_read_sources(self.team, calls, _CALL_AT - timedelta(days=3))

        assert [call_tables(call, sources) for call in calls] == [
            None,
            None,
            None,
            frozenset({"new_name", "events"}),
            frozenset({"events"}),
        ]

    def test_a_call_through_a_saved_expression_reads_its_tables(self) -> None:
        DataWarehouseExpression.objects.for_team(self.team.id).create(
            team=self.team,
            table_name="events",
            field_name="billing_total",
            expression="(SELECT sum(amount) FROM billing)",
        )
        call = _sql("SELECT billing_total FROM events")

        sources = load_read_sources(self.team, [call], _CALL_AT - timedelta(days=1))

        assert call_tables(call, sources) == frozenset({"events", "billing"})


class TestFetchCohorts(NonAtomicBaseTest):
    # ClickHouse reads `system.cohorts` from Postgres over its own connection, so the rows must be committed.
    CLASS_DATA_LEVEL_SETUP = False

    def test_reads_what_each_cohort_can_run(self) -> None:
        def filters(*values: dict[str, Any]) -> dict[str, Any]:
            return {"properties": {"type": "AND", "values": list(values)}}

        person = Cohort.objects.create(
            team=self.team, filters=filters({"type": "person", "key": "email", "value": "x"})
        )
        hogql = Cohort.objects.create(team=self.team, filters=filters(_HOGQL_FILTER))
        from_query = Cohort.objects.create(team=self.team, query={"kind": "HogQLQuery", "query": "SELECT 1"})
        static = Cohort.objects.create(team=self.team, is_static=True, filters=filters(_HOGQL_FILTER))

        cohorts = fetch_cohorts(self.team, [person.id, hogql.id, from_query.id, static.id])

        reads = cohort_reads({cohort.id: cohort for cohort in cohorts})
        assert reads == {person.id: True, hogql.id: False, from_query.id: False, static.id: True}
