from posthog.test.base import NonAtomicBaseTest

from parameterized import parameterized

from posthog.schema import AssistantTrendsEventsNode, AssistantTrendsQuery

from ee.hogai.context.insight.context import InsightContext


class TestInsightContext(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    @parameterized.expand(
        [
            ({"date_from": "-7d"}, None, None),
            (None, {"date_from": "-30d"}, None),
            ({"date_from": "-7d"}, {"date_to": "2025-01-01"}, {"var1": {"value": "test"}}),
        ]
    )
    async def test_get_effective_query_with_filters_no_sync_error(
        self, dashboard_filters, filters_override, variables_override
    ):
        """
        Verify that _get_effective_query does not throw SynchronousOnlyOperation
        when dashboard_filters/filters_override are provided.
        apply_dashboard_filters_to_dict calls get_query_runner which makes sync ORM calls,
        so we wrap it with database_sync_to_async.
        """
        query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        context = InsightContext(
            team=self.team,
            query=query,
            dashboard_filters=dashboard_filters,
            filters_override=filters_override,
            variables_override=variables_override,
        )

        # This should not raise SynchronousOnlyOperation
        effective_query = await context._get_effective_query()
        self.assertIsNotNone(effective_query)
