from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.schema import DataWarehouseNode, EventsNode, FunnelsQuery

from posthog.hogql_queries.insights.funnels.funnel_event_query import FunnelEventQuery
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext


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
    def test_funnel_event_query_only_dwh(self):
        pass
