from textwrap import dedent

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

import sqlparse

from posthog.schema import DataWarehouseNode, DataWarehousePropertyFilter, EventPropertyFilter, EventsNode, FunnelsQuery

from posthog.hogql import ast

from posthog.hogql_queries.insights.funnels.funnel_event_query import FunnelEventQuery
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext


def format_query(query: ast.SelectQuery):
    sql = str(query)[4:-1]
    return sqlparse.format(sql, keyword_case="upper", reindent=True)


class TestFunnelEventQuery(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    @freeze_time("2025-11-12")
    def test_funnel_event_query_simple(self):
        query = FunnelsQuery(series=[EventsNode(), EventsNode()])
        context = FunnelQueryContext(query=query, team=self.team)

        funnel_event_query = FunnelEventQuery(context=context).to_query()

        self.assertEqual(
            str(funnel_event_query),
            "sql("
            + "SELECT e.timestamp AS timestamp, person_id AS aggregation_target "
            + "FROM events AS e "
            + "WHERE and(greaterOrEquals(e.timestamp, toDateTime('2025-11-05 00:00:00.000000')), lessOrEquals(e.timestamp, toDateTime('2025-11-12 23:59:59.999999')))"
            ")",
        )

    @freeze_time("2025-11-12")
    def test_funnel_event_query_only_dwh(self):
        dwh_node = DataWarehouseNode(
            distinct_id_field="user_id",
            timestamp_field="created_at",
            table_name="payments",
            id="payments",
            id_field="id",
        )
        query = FunnelsQuery(series=[dwh_node, dwh_node])
        context = FunnelQueryContext(query=query, team=self.team)

        funnel_event_query = FunnelEventQuery(context=context).to_query()

        self.assertEqual(
            str(funnel_event_query),
            "sql("
            + "SELECT e.created_at AS timestamp, e.user_id AS aggregation_target "
            + "FROM payments AS e "
            + "WHERE and(greaterOrEquals(e.created_at, toDateTime('2025-11-05 00:00:00.000000')), lessOrEquals(e.created_at, toDateTime('2025-11-12 23:59:59.999999')))"
            ")",
        )

    @freeze_time("2025-11-12")
    def test_funnel_event_query_with_dwh(self):
        dwh_node = DataWarehouseNode(
            distinct_id_field="user_id",
            timestamp_field="created_at",
            table_name="payments",
            id="payments",
            id_field="id",
        )
        query = FunnelsQuery(series=[EventsNode(), dwh_node])
        context = FunnelQueryContext(query=query, team=self.team)

        funnel_event_query = FunnelEventQuery(context=context).to_query()

        self.assertEqual(
            str(funnel_event_query),
            "sql("
            + "SELECT e.timestamp AS timestamp, e.aggregation_target AS aggregation_target "
            + "FROM ("
            + "SELECT e.timestamp AS timestamp, person_id AS aggregation_target "
            + "FROM events AS e "
            + "WHERE and(greaterOrEquals(e.timestamp, toDateTime('2025-11-05 00:00:00.000000')), lessOrEquals(e.timestamp, toDateTime('2025-11-12 23:59:59.999999'))) "
            + "UNION ALL "
            + "SELECT e.created_at AS timestamp, e.user_id AS aggregation_target "
            + "FROM payments AS e "
            + "WHERE and(greaterOrEquals(e.created_at, toDateTime('2025-11-05 00:00:00.000000')), lessOrEquals(e.created_at, toDateTime('2025-11-12 23:59:59.999999')))"
            + ") AS e"
            ")",
        )

    @freeze_time("2025-11-12")
    def test_funnel_event_query_multiple_tables(self):
        query = FunnelsQuery(
            kind="FunnelsQuery",
            series=[
                EventsNode(
                    event="$pageview",
                    properties=[EventPropertyFilter(key="$browser", value=["Opera"], operator="exact")],
                ),
                DataWarehouseNode(
                    id="table_one",
                    table_name="table_one",
                    id_field="id",
                    distinct_id_field="user_id",
                    timestamp_field="created_at",
                    properties=[DataWarehousePropertyFilter(key="some_prop", value="some_value", operator="exact")],
                ),
                DataWarehouseNode(
                    id="table_two",
                    table_name="table_two",
                    id_field="some_id",
                    distinct_id_field="some_user_id",
                    timestamp_field="ts",
                    properties=[
                        DataWarehousePropertyFilter(key="another_prop", value="another_value", operator="exact")
                    ],
                ),
                DataWarehouseNode(
                    id="table_one",
                    table_name="table_one",
                    id_field="id",
                    distinct_id_field="user_id",
                    timestamp_field="created_at",
                    properties=[DataWarehousePropertyFilter(key="other_prop", value="other_value", operator="exact")],
                ),
            ],
        )
        context = FunnelQueryContext(query=query, team=self.team)

        funnel_event_query = FunnelEventQuery(context=context).to_query()

        select_1 = format_query(funnel_event_query.select_from.table.initial_select_query)
        expected_1 = dedent("""
            SELECT e.timestamp AS timestamp,
                   person_id AS aggregation_target,
                   if(and(equals(event, '$pageview'), equals(properties.$browser, 'Opera')), 1, 0) AS step_0,
                   0 AS step_1,
                   0 AS step_2,
                   0 AS step_3
            FROM EVENTS AS e
            WHERE and(and(and(greaterOrEquals(e.timestamp, toDateTime('2025-11-05 00:00:00.000000')), lessOrEquals(e.timestamp, toDateTime('2025-11-12 23:59:59.999999'))), IN(event, tuple('$pageview'))), equals(step_0, 1))
        """).strip()
        self.assertEqual(select_1, expected_1)

        select_2 = format_query(funnel_event_query.select_from.table.subsequent_select_queries[0].select_query)
        expected_2 = dedent("""
            SELECT e.created_at AS timestamp,
                   toUUID(e.user_id) AS aggregation_target,
                   0 AS step_0,
                   if(and(1, equals(some_prop, 'some_value')), 1, 0) AS step_1,
                   if(and(0, equals(another_prop, 'another_value')), 1, 0) AS step_2,
                   if(and(1, equals(other_prop, 'other_value')), 1, 0) AS step_3
            FROM table_one AS e
            WHERE and(and(greaterOrEquals(e.created_at, toDateTime('2025-11-05 00:00:00.000000')), lessOrEquals(e.created_at, toDateTime('2025-11-12 23:59:59.999999'))), or(equals(step_1, 1), equals(step_3, 1)))
        """).strip()
        self.assertEqual(select_2, expected_2)

        select_3 = format_query(funnel_event_query.select_from.table.subsequent_select_queries[1].select_query)
