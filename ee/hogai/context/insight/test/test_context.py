from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import AssistantTrendsEventsNode, AssistantTrendsQuery

from ee.hogai.context.insight.context import InsightContext
from ee.hogai.tool_errors import MaxToolRetryableError


class TestInsightContext(BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def test_initialization_with_all_parameters(self):
        query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        context = InsightContext(
            team=self.team,
            query=query,
            name="Test Insight",
            description="Test Description",
            insight_id="test_id",
            insight_model_id=123,
            dashboard_filters={"date_from": "-7d"},
            filters_override={"date_to": "2025-01-01"},
            variables_override={"var1": {"value": "test"}},
        )

        self.assertEqual(context.team, self.team)
        self.assertEqual(context.query, query)
        self.assertEqual(context.name, "Test Insight")
        self.assertEqual(context.description, "Test Description")
        self.assertEqual(context.insight_id, "test_id")
        self.assertEqual(context.insight_model_id, 123)
        self.assertEqual(context.dashboard_filters, {"date_from": "-7d"})
        self.assertEqual(context.filters_override, {"date_to": "2025-01-01"})
        self.assertEqual(context.variables_override, {"var1": {"value": "test"}})

    def test_initialization_with_minimal_parameters(self):
        query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        context = InsightContext(team=self.team, query=query)

        self.assertEqual(context.team, self.team)
        self.assertEqual(context.query, query)
        self.assertIsNone(context.name)
        self.assertIsNone(context.description)
        self.assertIsNone(context.insight_id)
        self.assertIsNone(context.insight_model_id)
        self.assertIsNone(context.dashboard_filters)
        self.assertIsNone(context.filters_override)
        self.assertIsNone(context.variables_override)

    async def test_get_effective_query_no_filters(self):
        query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        context = InsightContext(team=self.team, query=query)

        effective_query = await context._get_effective_query()

        self.assertEqual(effective_query, query)

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
        query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        context = InsightContext(
            team=self.team,
            query=query,
            dashboard_filters=dashboard_filters,
            filters_override=filters_override,
            variables_override=variables_override,
        )

        effective_query = await context._get_effective_query()
        self.assertIsNotNone(effective_query)

    @patch("ee.hogai.context.insight.context.execute_and_format_query")
    async def test_execute_and_format_successful_execution(self, mock_execute):
        mock_execute.return_value = "Test Results"

        query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        context = InsightContext(
            team=self.team,
            query=query,
            name="Test Insight",
            description="Test Description",
            insight_id="test_id",
            insight_model_id=123,
        )

        result = await context.execute_and_format()

        self.assertIn("Test Results", result)
        self.assertIn("Test Insight", result)
        self.assertIn("Test Description", result)
        self.assertIn("test_id", result)
        mock_execute.assert_called_once()

    @patch("ee.hogai.context.insight.context.execute_and_format_query")
    async def test_execute_and_format_with_default_name(self, mock_execute):
        mock_execute.return_value = "Test Results"

        query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        context = InsightContext(team=self.team, query=query)

        result = await context.execute_and_format()

        self.assertIn("Insight", result)
        mock_execute.assert_called_once()

    @patch("ee.hogai.context.insight.context.execute_and_format_query")
    async def test_execute_and_format_with_custom_template(self, mock_execute):
        mock_execute.return_value = "Test Results"

        custom_template = "Custom: {{{insight_name}}} - {{{results}}}"
        query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        context = InsightContext(team=self.team, query=query, name="My Insight")

        result = await context.execute_and_format(prompt_template=custom_template)

        self.assertIn("Custom:", result)
        self.assertIn("My Insight", result)
        self.assertIn("Test Results", result)

    @patch("ee.hogai.context.insight.context.execute_and_format_query")
    async def test_execute_and_format_raises_error_by_default(self, mock_execute):
        mock_execute.side_effect = Exception("Query failed")

        query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        context = InsightContext(team=self.team, query=query)

        with self.assertRaises(MaxToolRetryableError) as exc:
            await context.execute_and_format()

        self.assertIn("Error executing query: Query failed", str(exc.exception))

    @patch("ee.hogai.context.insight.context.execute_and_format_query")
    async def test_execute_and_format_returns_exception_when_flag_set(self, mock_execute):
        mock_execute.side_effect = Exception("Query failed")

        query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        context = InsightContext(team=self.team, query=query, name="Test Insight")

        result = await context.execute_and_format(return_exceptions=True)

        self.assertIn("Error executing query: Query failed", result)
        self.assertIn("Test Insight", result)

    async def test_format_schema_basic(self):
        query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        context = InsightContext(
            team=self.team, query=query, name="Test Insight", description="Test Description", insight_id="test_id"
        )

        result = await context.format_schema()

        self.assertIn("Test Insight", result)
        self.assertIn("Test Description", result)
        self.assertIn("test_id", result)
        self.assertIn('"kind":"TrendsQuery"', result)
        self.assertIn("$pageview", result)

    async def test_format_schema_with_custom_template(self):
        custom_template = "Schema: {{{query_schema}}}"
        query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        context = InsightContext(team=self.team, query=query)

        result = await context.format_schema(prompt_template=custom_template)

        self.assertIn("Schema:", result)
        self.assertIn('"kind":"TrendsQuery"', result)

    async def test_format_schema_without_optional_fields(self):
        query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        context = InsightContext(team=self.team, query=query)

        result = await context.format_schema()

        self.assertNotIn("Insight ID:", result)
        self.assertNotIn("Description:", result)

    @patch("ee.hogai.context.insight.context.execute_and_format_query")
    async def test_execute_and_format_applies_dashboard_filters(self, mock_execute):
        mock_execute.return_value = "Test Results"

        query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        context = InsightContext(team=self.team, query=query, dashboard_filters={"date_from": "-7d"})

        await context.execute_and_format()

        call_args = mock_execute.call_args
        executed_query = call_args[0][1]
        self.assertIsNotNone(executed_query)

    @patch("ee.hogai.context.insight.context.execute_and_format_query")
    async def test_execute_and_format_with_insight_model_id(self, mock_execute):
        mock_execute.return_value = "Test Results"

        query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        context = InsightContext(
            team=self.team,
            query=query,
            insight_model_id=456,
        )

        await context.execute_and_format()

        call_args = mock_execute.call_args
        insight_id_kwarg = call_args[1].get("insight_id")
        self.assertEqual(insight_id_kwarg, 456)

    async def test_format_schema_applies_dashboard_filters(self):
        query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        context = InsightContext(team=self.team, query=query, dashboard_filters={"date_from": "-7d"})

        result = await context.format_schema()

        self.assertIn('"kind":"TrendsQuery"', result)

    @parameterized.expand(
        [
            ({"date_from": "-7d"}, None, None),
            (None, {"date_from": "-30d"}, None),
            (None, None, {"var1": {"value": "test"}}),
            ({"date_from": "-7d"}, {"date_to": "2025-01-01"}, {"var1": {"value": "test"}}),
        ]
    )
    async def test_get_effective_query_with_various_filter_combinations(
        self, dashboard_filters, filters_override, variables_override
    ):
        query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        context = InsightContext(
            team=self.team,
            query=query,
            dashboard_filters=dashboard_filters,
            filters_override=filters_override,
            variables_override=variables_override,
        )

        effective_query = await context._get_effective_query()

        self.assertIsNotNone(effective_query)

    def test_insight_url_is_none_when_no_short_id(self):
        query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        context = InsightContext(team=self.team, query=query)

        self.assertIsNone(context.insight_url)

    def test_insight_url_generated_from_short_id(self):
        query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        context = InsightContext(team=self.team, query=query, insight_short_id="abc123")

        self.assertEqual(context.insight_url, f"/project/{self.team.id}/insights/abc123")

    @patch("ee.hogai.context.insight.context.execute_and_format_query")
    async def test_execute_and_format_includes_insight_url(self, mock_execute):
        mock_execute.return_value = "Test Results"

        query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        context = InsightContext(
            team=self.team,
            query=query,
            name="Test Insight",
            insight_id="display-id",
            insight_short_id="xyz789",
        )

        result = await context.execute_and_format()

        self.assertIn(f"/project/{self.team.id}/insights/xyz789", result)

    @patch("ee.hogai.context.insight.context.execute_and_format_query")
    async def test_execute_and_format_shows_fallback_when_no_url(self, mock_execute):
        mock_execute.return_value = "Test Results"

        query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        context = InsightContext(
            team=self.team,
            query=query,
            name="Test Insight",
        )

        result = await context.execute_and_format()

        self.assertIn("This insight cannot be accessed via a URL.", result)
