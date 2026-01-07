from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.schema import EventsNode, TrendsQuery

from ee.hogai.context.dashboard.context import DashboardContext, DashboardInsightContext
import pytest


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

        assert "Dashboard name: Empty Dashboard" in result
        assert "Dashboard ID: 123" in result
        assert "Description: A dashboard with no insights" in result

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

        assert "Dashboard name: Test Dashboard" in result
        assert "Dashboard ID: 456" in result
        assert "Description: Dashboard description" in result
        assert "Test Insight" in result
        assert "Insight results: 100 users" in result
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

        assert "Dashboard name: Multi-Insight Dashboard" in result
        assert "Insight 1" in result
        assert "Insight 2" in result
        assert "Insight 3" in result
        assert "First insight results" in result
        assert "Second insight results" in result
        assert "Third insight results" in result
        assert mock_execute.call_count == 3

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

        assert "Dashboard name: Partially Failed Dashboard" in result
        assert "Success result" in result
        assert "Another success" in result
        # Failed insight error message should be in results
        assert "Error executing query" in result

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

        assert "Dashboard name: Schema Dashboard" in result
        assert "Dashboard ID: 202" in result
        assert "Description: Dashboard for schema test" in result

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

        assert "Dashboard name: Schema Dashboard" in result
        assert "Schema Insight 1" in result
        assert "Schema Insight 2" in result
        assert "First insight" in result
        # Schema should include query JSON
        assert "TrendsQuery" in result
        # Should NOT include results
        assert "Results:" not in result

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
        with pytest.raises(Exception) as context:
            await dashboard_ctx.format_schema()

        assert "Schema error" in str(context.value)

    async def test_dashboard_without_id(self):
        """Test that dashboard works without an ID"""
        dashboard_ctx = DashboardContext(
            team=self.team,
            insights_data=[],
            name="No ID Dashboard",
        )

        result = await dashboard_ctx.format_schema()

        assert "Dashboard name: No ID Dashboard" in result
        assert "Dashboard ID:" not in result

    async def test_dashboard_without_name(self):
        """Test that dashboard works without a name"""
        dashboard_ctx = DashboardContext(
            team=self.team,
            insights_data=[],
            dashboard_id="606",
        )

        result = await dashboard_ctx.format_schema()

        assert "Dashboard name: Dashboard" in result
        assert "Dashboard ID: 606" in result

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
        assert dashboard_ctx._semaphore._value == 5

        result = await dashboard_ctx.execute_and_format()

        assert "Concurrent Dashboard" in result
        assert mock_execute.call_count == 10

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

        assert "Custom: Custom Template Dashboard" in result
        assert "Custom template result" in result
