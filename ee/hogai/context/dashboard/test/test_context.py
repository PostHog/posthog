from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.schema import EventsNode, TrendsQuery

from ee.hogai.context.dashboard.context import DashboardContext, DashboardInsightContext


class TestDashboardContext(BaseTest):
    async def test_execute_with_no_insights(self):
        """Test that execute returns formatted dashboard with no insights"""
        dashboard_ctx = DashboardContext(
            team=self.team,
            insights_data=[],
            name="Empty Dashboard",
            description="A dashboard with no insights",
            dashboard_id="123",
        )

        result = await dashboard_ctx.execute_and_format()

        self.assertIn("Dashboard name: Empty Dashboard", result)
        self.assertIn("Dashboard ID: 123", result)
        self.assertIn("Description: A dashboard with no insights", result)

    @patch("ee.hogai.context.insight.context.execute_and_format_query")
    async def test_execute_with_single_insight(self, mock_execute):
        """Test that execute runs a single insight and formats the result"""
        mock_execute.return_value = "Insight results: 100 users"

        insights_data: list[DashboardInsightContext] = [
            DashboardInsightContext(
                query=TrendsQuery(series=[EventsNode(event="pageview")]),
                name="Test Insight",
                description="Test description",
                insight_id="insight-1",
            )
        ]

        dashboard_ctx = DashboardContext(
            team=self.team,
            insights_data=insights_data,
            name="Test Dashboard",
            description="Dashboard description",
            dashboard_id="456",
        )

        result = await dashboard_ctx.execute_and_format()

        self.assertIn("Dashboard name: Test Dashboard", result)
        self.assertIn("Dashboard ID: 456", result)
        self.assertIn("Description: Dashboard description", result)
        self.assertIn("Test Insight", result)
        self.assertIn("Insight results: 100 users", result)
        mock_execute.assert_called_once()

    @patch("ee.hogai.context.insight.context.execute_and_format_query")
    async def test_execute_with_multiple_insights(self, mock_execute):
        """Test that execute runs multiple insights in parallel"""
        mock_execute.side_effect = [
            "First insight results",
            "Second insight results",
            "Third insight results",
        ]

        insights_data: list[DashboardInsightContext] = [
            DashboardInsightContext(
                query=TrendsQuery(series=[EventsNode(event="pageview")]),
                name=f"Insight {i}",
                insight_id=f"insight-{i}",
            )
            for i in range(1, 4)
        ]

        dashboard_ctx = DashboardContext(
            team=self.team,
            insights_data=insights_data,
            name="Multi-Insight Dashboard",
            dashboard_id="789",
        )

        result = await dashboard_ctx.execute_and_format()

        self.assertIn("Dashboard name: Multi-Insight Dashboard", result)
        self.assertIn("Insight 1", result)
        self.assertIn("Insight 2", result)
        self.assertIn("Insight 3", result)
        self.assertIn("First insight results", result)
        self.assertIn("Second insight results", result)
        self.assertIn("Third insight results", result)
        self.assertEqual(mock_execute.call_count, 3)

    @patch("ee.hogai.context.insight.context.execute_and_format_query")
    async def test_execute_with_failed_insights(self, mock_execute):
        """Test that execute handles failed insights gracefully"""
        mock_execute.side_effect = [
            "Success result",
            Exception("Query failed"),
            "Another success",
        ]

        insights_data: list[DashboardInsightContext] = [
            DashboardInsightContext(
                query=TrendsQuery(series=[EventsNode(event="pageview")]),
                name=f"Insight {i}",
                insight_id=f"insight-{i}",
            )
            for i in range(1, 4)
        ]

        dashboard_ctx = DashboardContext(
            team=self.team,
            insights_data=insights_data,
            name="Partially Failed Dashboard",
            dashboard_id="101",
        )

        result = await dashboard_ctx.execute_and_format()

        self.assertIn("Dashboard name: Partially Failed Dashboard", result)
        self.assertIn("Success result", result)
        self.assertIn("Another success", result)
        # Failed insight error message should be in results
        self.assertIn("Error executing query", result)

    async def test_format_schema_with_no_insights(self):
        """Test that format_schema returns formatted dashboard without execution"""
        dashboard_ctx = DashboardContext(
            team=self.team,
            insights_data=[],
            name="Schema Dashboard",
            description="Dashboard for schema test",
            dashboard_id="202",
        )

        result = await dashboard_ctx.format_schema()

        self.assertIn("Dashboard name: Schema Dashboard", result)
        self.assertIn("Dashboard ID: 202", result)
        self.assertIn("Description: Dashboard for schema test", result)

    async def test_format_schema_with_insights(self):
        """Test that format_schema returns insight schemas without execution"""
        insights_data: list[DashboardInsightContext] = [
            DashboardInsightContext(
                query=TrendsQuery(series=[EventsNode(event="pageview")]),
                name="Schema Insight 1",
                description="First insight",
                insight_id="insight-1",
            ),
            DashboardInsightContext(
                query=TrendsQuery(series=[EventsNode(event="click")]),
                name="Schema Insight 2",
                insight_id="insight-2",
            ),
        ]

        dashboard_ctx = DashboardContext(
            team=self.team,
            insights_data=insights_data,
            name="Schema Dashboard",
            dashboard_id="303",
        )

        result = await dashboard_ctx.format_schema()

        self.assertIn("Dashboard name: Schema Dashboard", result)
        self.assertIn("Schema Insight 1", result)
        self.assertIn("Schema Insight 2", result)
        self.assertIn("First insight", result)
        # Schema should include query JSON
        self.assertIn("TrendsQuery", result)
        # Should NOT include results
        self.assertNotIn("Results:", result)

    @patch("ee.hogai.context.insight.context.InsightContext.format_schema")
    async def test_format_schema_handles_exceptions(self, mock_format_schema):
        """Test that format_schema propagates exceptions in insight schema formatting"""
        mock_format_schema.side_effect = Exception("Schema error")

        insights_data: list[DashboardInsightContext] = [
            DashboardInsightContext(
                query=TrendsQuery(series=[EventsNode(event="pageview")]),
                name="Failing Insight",
                insight_id="fail",
            )
        ]

        dashboard_ctx = DashboardContext(
            team=self.team,
            insights_data=insights_data,
            name="Error Dashboard",
            dashboard_id="404",
        )

        # Exception should propagate
        with self.assertRaises(Exception) as context:
            await dashboard_ctx.format_schema()

        self.assertIn("Schema error", str(context.exception))

    async def test_dashboard_without_id(self):
        """Test that dashboard works without an ID"""
        dashboard_ctx = DashboardContext(
            team=self.team,
            insights_data=[],
            name="No ID Dashboard",
        )

        result = await dashboard_ctx.format_schema()

        self.assertIn("Dashboard name: No ID Dashboard", result)
        self.assertNotIn("Dashboard ID:", result)

    async def test_dashboard_without_name(self):
        """Test that dashboard works without a name"""
        dashboard_ctx = DashboardContext(
            team=self.team,
            insights_data=[],
            dashboard_id="606",
        )

        result = await dashboard_ctx.format_schema()

        self.assertIn("Dashboard name: Dashboard", result)
        self.assertIn("Dashboard ID: 606", result)

    @patch("ee.hogai.context.insight.context.execute_and_format_query")
    async def test_custom_max_concurrent_queries(self, mock_execute):
        """Test that custom max_concurrent_queries is respected"""
        mock_execute.return_value = "Concurrent result"

        insights_data: list[DashboardInsightContext] = [
            DashboardInsightContext(
                query=TrendsQuery(series=[EventsNode(event="pageview")]),
                name=f"Insight {i}",
                insight_id=f"insight-{i}",
            )
            for i in range(10)
        ]

        dashboard_ctx = DashboardContext(
            team=self.team,
            insights_data=insights_data,
            name="Concurrent Dashboard",
            dashboard_id="707",
            max_concurrent_queries=5,
        )

        # Verify semaphore is set correctly
        self.assertEqual(dashboard_ctx._semaphore._value, 5)

        result = await dashboard_ctx.execute_and_format()

        self.assertIn("Concurrent Dashboard", result)
        self.assertEqual(mock_execute.call_count, 10)

    @patch("ee.hogai.context.insight.context.execute_and_format_query")
    async def test_custom_prompt_template(self, mock_execute):
        """Test that custom prompt template is used"""
        mock_execute.return_value = "Custom template result"

        insights_data: list[DashboardInsightContext] = [
            DashboardInsightContext(
                query=TrendsQuery(series=[EventsNode(event="pageview")]),
                name="Custom Template Insight",
                insight_id="custom-1",
            )
        ]

        dashboard_ctx = DashboardContext(
            team=self.team,
            insights_data=insights_data,
            name="Custom Template Dashboard",
            dashboard_id="808",
        )

        custom_template = "Custom: {{{dashboard_name}}} - {{{insights}}}"
        result = await dashboard_ctx.execute_and_format(prompt_template=custom_template)

        self.assertIn("Custom: Custom Template Dashboard", result)
        self.assertIn("Custom template result", result)
