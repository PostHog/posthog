from freezegun import freeze_time
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.insights.funnels.funnel import Funnel
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.schema import EventsNode, FunnelsQuery
from posthog.test.base import BaseTest


class TestFunnelStepCountsWithoutAggregationQuery(BaseTest):
    maxDiff = None

    def test_smoke(self):
        with freeze_time("2024-01-10T12:01:00"):
            query = FunnelsQuery(series=[EventsNode(), EventsNode()])
            funnel_class = Funnel(context=FunnelQueryContext(query=query, team=self.team))

        query_ast = funnel_class.get_step_counts_without_aggregation_query()
        response = execute_hogql_query(query_type="FunnelsQuery", query=query_ast, team=self.team)

        self.assertEqual(
            response.hogql,
            "SELECT aggregation_target, timestamp, step_0, latest_0, step_1, latest_1 FROM (SELECT aggregation_target, timestamp, step_0, latest_0, step_1, min(latest_1) OVER (PARTITION BY aggregation_target ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS latest_1 FROM (SELECT e.timestamp AS timestamp, person_id AS aggregation_target, if(true, 1, 0) AS step_0, if(equals(step_0, 1), timestamp, NULL) AS latest_0, if(true, 1, 0) AS step_1, if(equals(step_1, 1), timestamp, NULL) AS latest_1 FROM events AS e WHERE and(greaterOrEquals(e.timestamp, toDateTime('2024-01-03 00:00:00.000000')), lessOrEquals(e.timestamp, toDateTime('2024-01-10 23:59:59.999999'))))) WHERE equals(step_0, 1) LIMIT 100",
        )


class TestFunnelStepCounts(BaseTest):
    maxDiff = None

    def test_smoke(self):
        with freeze_time("2024-01-10T12:01:00"):
            query = FunnelsQuery(series=[EventsNode(), EventsNode()])
            funnel_class = Funnel(context=FunnelQueryContext(query=query, team=self.team))

        query_ast = funnel_class.get_step_counts_query()
        response = execute_hogql_query(query_type="FunnelsQuery", query=query_ast, team=self.team)

        self.assertEqual(
            response.hogql,
            "SELECT aggregation_target, timestamp, step_0, latest_0, step_1, latest_1 FROM (SELECT aggregation_target, timestamp, step_0, latest_0, step_1, min(latest_1) OVER (PARTITION BY aggregation_target ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS latest_1 FROM (SELECT e.timestamp AS timestamp, person_id AS aggregation_target, if(true, 1, 0) AS step_0, if(equals(step_0, 1), timestamp, NULL) AS latest_0, if(true, 1, 0) AS step_1, if(equals(step_1, 1), timestamp, NULL) AS latest_1 FROM events AS e WHERE and(greaterOrEquals(e.timestamp, toDateTime('2024-01-03 00:00:00.000000')), lessOrEquals(e.timestamp, toDateTime('2024-01-10 23:59:59.999999'))))) WHERE equals(step_0, 1) LIMIT 100",
        )
