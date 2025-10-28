from typing import cast
from uuid import uuid4

from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.schema import AssistantMessage

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.graph.root.tools.create_dashboard import CreateDashboardTool
from ee.hogai.utils.types import AssistantState, InsightQuery, PartialAssistantState


class TestCreateDashboardTool(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.tool_call_id = str(uuid4())
        self.state = AssistantState(messages=[], root_tool_call_id=self.tool_call_id)
        self.context_manager = AssistantContextManager(self.team, self.user, {})
        self.tool = CreateDashboardTool(
            team=self.team,
            user=self.user,
            state=self.state,
            context_manager=self.context_manager,
        )

    async def test_execute_calls_dashboard_creation_node(self):
        mock_node_instance = MagicMock()
        mock_result = PartialAssistantState(
            messages=[AssistantMessage(content="Dashboard created successfully with 3 insights")]
        )

        with patch("ee.hogai.graph.dashboards.nodes.DashboardCreationNode", return_value=mock_node_instance):
            with patch("ee.hogai.graph.root.tools.create_dashboard.RunnableLambda") as mock_runnable:
                mock_chain = MagicMock()
                mock_chain.ainvoke = AsyncMock(return_value=mock_result)
                mock_runnable.return_value = mock_chain

                insight_queries = [
                    InsightQuery(name="Pageviews", description="Show pageviews for last 7 days"),
                    InsightQuery(name="User signups", description="Show user signups funnel"),
                ]

                result, artifact = await self.tool._arun_impl(
                    search_insights_queries=insight_queries,
                    dashboard_name="Marketing Dashboard",
                    tool_call_id="test-tool-call-id",
                )

                self.assertEqual(result, "")
                self.assertIsNotNone(artifact)
                assert artifact is not None
                self.assertEqual(len(artifact.messages), 1)
                message = cast(AssistantMessage, artifact.messages[0])
                self.assertEqual(message.content, "Dashboard created successfully with 3 insights")

    async def test_execute_updates_state_with_all_parameters(self):
        mock_result = PartialAssistantState(messages=[AssistantMessage(content="Test response")])

        insight_queries = [
            InsightQuery(name="Revenue Trends", description="Monthly revenue trends for Q4"),
            InsightQuery(name="Churn Rate", description="Customer churn rate by cohort"),
            InsightQuery(name="NPS Score", description="Net Promoter Score over time"),
        ]

        async def mock_ainvoke(state):
            self.assertEqual(state.search_insights_queries, insight_queries)
            self.assertEqual(state.dashboard_name, "Executive Summary Q4")
            self.assertEqual(state.root_tool_call_id, "custom-tool-call-id")
            return mock_result

        mock_chain = MagicMock()
        mock_chain.ainvoke = mock_ainvoke

        with patch("ee.hogai.graph.dashboards.nodes.DashboardCreationNode"):
            with patch("ee.hogai.graph.root.tools.create_dashboard.RunnableLambda", return_value=mock_chain):
                await self.tool._arun_impl(
                    search_insights_queries=insight_queries,
                    dashboard_name="Executive Summary Q4",
                    tool_call_id="custom-tool-call-id",
                )

    async def test_execute_with_single_insight_query(self):
        mock_result = PartialAssistantState(messages=[AssistantMessage(content="Dashboard with one insight created")])

        insight_queries = [InsightQuery(name="Daily Active Users", description="Count of daily active users")]

        async def mock_ainvoke(state):
            self.assertEqual(len(state.search_insights_queries), 1)
            self.assertEqual(state.search_insights_queries[0].name, "Daily Active Users")
            self.assertEqual(state.search_insights_queries[0].description, "Count of daily active users")
            self.assertEqual(state.dashboard_name, "User Activity Dashboard")
            return mock_result

        mock_chain = MagicMock()
        mock_chain.ainvoke = mock_ainvoke

        with patch("ee.hogai.graph.dashboards.nodes.DashboardCreationNode"):
            with patch("ee.hogai.graph.root.tools.create_dashboard.RunnableLambda", return_value=mock_chain):
                result, artifact = await self.tool._arun_impl(
                    search_insights_queries=insight_queries,
                    dashboard_name="User Activity Dashboard",
                    tool_call_id="test-id",
                )

                self.assertEqual(result, "")
                self.assertIsNotNone(artifact)

    async def test_execute_with_many_insight_queries(self):
        mock_result = PartialAssistantState(messages=[AssistantMessage(content="Large dashboard created")])

        insight_queries = [
            InsightQuery(name=f"Insight {i}", description=f"Description for insight {i}") for i in range(10)
        ]

        async def mock_ainvoke(state):
            self.assertEqual(len(state.search_insights_queries), 10)
            self.assertEqual(state.search_insights_queries[0].name, "Insight 0")
            self.assertEqual(state.search_insights_queries[9].name, "Insight 9")
            self.assertEqual(state.dashboard_name, "Comprehensive Dashboard")
            return mock_result

        mock_chain = MagicMock()
        mock_chain.ainvoke = mock_ainvoke

        with patch("ee.hogai.graph.dashboards.nodes.DashboardCreationNode"):
            with patch("ee.hogai.graph.root.tools.create_dashboard.RunnableLambda", return_value=mock_chain):
                result, artifact = await self.tool._arun_impl(
                    search_insights_queries=insight_queries,
                    dashboard_name="Comprehensive Dashboard",
                    tool_call_id="test-id",
                )

                self.assertEqual(result, "")
                self.assertIsNotNone(artifact)

    async def test_execute_returns_failure_message_when_result_is_none(self):
        async def mock_ainvoke(state):
            return None

        mock_chain = MagicMock()
        mock_chain.ainvoke = mock_ainvoke

        with patch("ee.hogai.graph.dashboards.nodes.DashboardCreationNode"):
            with patch("ee.hogai.graph.root.tools.create_dashboard.RunnableLambda", return_value=mock_chain):
                result, artifact = await self.tool._arun_impl(
                    search_insights_queries=[InsightQuery(name="Test", description="Test insight")],
                    dashboard_name="Test Dashboard",
                    tool_call_id="test-tool-call-id",
                )

                self.assertEqual(result, "Dashboard creation failed")
                self.assertIsNone(artifact)

    async def test_execute_returns_failure_message_when_result_has_no_messages(self):
        mock_result = PartialAssistantState(messages=[])

        async def mock_ainvoke(state):
            return mock_result

        mock_chain = MagicMock()
        mock_chain.ainvoke = mock_ainvoke

        with patch("ee.hogai.graph.dashboards.nodes.DashboardCreationNode"):
            with patch("ee.hogai.graph.root.tools.create_dashboard.RunnableLambda", return_value=mock_chain):
                result, artifact = await self.tool._arun_impl(
                    search_insights_queries=[InsightQuery(name="Test", description="Test insight")],
                    dashboard_name="Test Dashboard",
                    tool_call_id="test-tool-call-id",
                )

                self.assertEqual(result, "Dashboard creation failed")
                self.assertIsNone(artifact)

    async def test_execute_preserves_original_state(self):
        """Test that the original state is not modified when creating the copied state"""
        original_queries = [InsightQuery(name="Original", description="Original insight")]
        original_state = AssistantState(
            messages=[],
            root_tool_call_id="original-id",
            search_insights_queries=original_queries,
            dashboard_name="Original Dashboard",
        )

        tool = CreateDashboardTool(
            team=self.team,
            user=self.user,
            state=original_state,
            context_manager=self.context_manager,
        )

        mock_result = PartialAssistantState(messages=[AssistantMessage(content="Test")])

        new_queries = [InsightQuery(name="New", description="New insight")]

        async def mock_ainvoke(state):
            # Verify the new state has updated values
            self.assertEqual(state.search_insights_queries, new_queries)
            self.assertEqual(state.dashboard_name, "New Dashboard")
            self.assertEqual(state.root_tool_call_id, "new-id")
            return mock_result

        mock_chain = MagicMock()
        mock_chain.ainvoke = mock_ainvoke

        with patch("ee.hogai.graph.dashboards.nodes.DashboardCreationNode"):
            with patch("ee.hogai.graph.root.tools.create_dashboard.RunnableLambda", return_value=mock_chain):
                await tool._arun_impl(
                    search_insights_queries=new_queries,
                    dashboard_name="New Dashboard",
                    tool_call_id="new-id",
                )

        # Verify original state was not modified
        self.assertEqual(original_state.search_insights_queries, original_queries)
        self.assertEqual(original_state.dashboard_name, "Original Dashboard")
        self.assertEqual(original_state.root_tool_call_id, "original-id")

    async def test_execute_with_complex_insight_descriptions(self):
        """Test that complex insight descriptions with special characters are handled correctly"""
        mock_result = PartialAssistantState(messages=[AssistantMessage(content="Dashboard created")])

        insight_queries = [
            InsightQuery(
                name="User Journey",
                description='Show funnel from "Sign up" → "Create project" → "Invite team" for users with property email containing "@company.com"',
            ),
            InsightQuery(
                name="Revenue (USD)",
                description="Track total revenue in USD from 2024-01-01 to 2024-12-31, filtered by plan_type = 'premium' OR plan_type = 'enterprise'",
            ),
        ]

        async def mock_ainvoke(state):
            self.assertEqual(len(state.search_insights_queries), 2)
            self.assertIn("@company.com", state.search_insights_queries[0].description)
            self.assertIn("'premium'", state.search_insights_queries[1].description)
            return mock_result

        mock_chain = MagicMock()
        mock_chain.ainvoke = mock_ainvoke

        with patch("ee.hogai.graph.dashboards.nodes.DashboardCreationNode"):
            with patch("ee.hogai.graph.root.tools.create_dashboard.RunnableLambda", return_value=mock_chain):
                result, artifact = await self.tool._arun_impl(
                    search_insights_queries=insight_queries,
                    dashboard_name="Complex Dashboard",
                    tool_call_id="test-id",
                )

                self.assertEqual(result, "")
                self.assertIsNotNone(artifact)
