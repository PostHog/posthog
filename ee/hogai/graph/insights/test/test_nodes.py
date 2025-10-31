import asyncio
from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

from posthog.schema import (
    AssistantToolCallMessage,
    DataTableNode,
    EntityType,
    FunnelsQuery,
    HogQLQuery,
    HumanMessage,
    InsightVizNode,
    RetentionEntity,
    RetentionFilter,
    RetentionQuery,
    TrendsQuery,
    VisualizationMessage,
)

from posthog.models import Insight, InsightViewed

from ee.hogai.graph.insights.nodes import InsightDict, InsightSearchNode, NoInsightsException
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.models.assistant import Conversation


def create_mock_query_executor():
    """Mock query executor instead of querying ClickHouse (since we are using NonAtomicBaseTest)"""
    mock_executor = MagicMock()

    async def mock_arun_and_format_query(query_obj):
        """Return mocked query results based on query type."""
        if isinstance(query_obj, TrendsQuery):
            return "Mocked trends query results: Daily pageviews = 1000", {}
        elif isinstance(query_obj, FunnelsQuery):
            return "Mocked funnel query results: Conversion rate = 25%", {}
        elif isinstance(query_obj, RetentionQuery):
            return "Mocked retention query results: Day 1 retention = 40%", {}
        elif isinstance(query_obj, HogQLQuery):
            return "Mocked HogQL query results: Result count = 42", {}
        else:
            return "Mocked query results", {}

    mock_executor.arun_and_format_query = mock_arun_and_format_query
    return mock_executor


@patch("ee.hogai.graph.insights.nodes.AssistantQueryExecutor", create_mock_query_executor)
class TestInsightSearchNode(BaseTest):
    def setUp(self):
        super().setUp()
        self.node = InsightSearchNode(self.team, self.user)

        # Create test insights
        self.insight1 = Insight.objects.create(
            team=self.team,
            name="Daily Pageviews",
            description="Track daily website traffic",
            query={
                "source": {
                    "kind": "TrendsQuery",
                    "series": [{"event": "$pageview", "kind": "EventsNode"}],
                    "dateRange": {"date_from": "-7d"},
                }
            },
            filters={"insight": "TRENDS"},
            created_by=self.user,
        )

        self.insight2 = Insight.objects.create(
            team=self.team,
            name="User Signup Funnel",
            description="Track user conversion through signup",
            query={
                "source": {
                    "kind": "FunnelsQuery",
                    "series": [
                        {"event": "signup_start", "kind": "EventsNode"},
                        {"event": "signup_complete", "kind": "EventsNode"},
                    ],
                    "dateRange": {"date_from": "-7d"},
                }
            },
            filters={"insight": "FUNNELS"},
            created_by=self.user,
        )

        # Create InsightViewed records
        InsightViewed.objects.create(
            team=self.team,
            user=self.user,
            insight=self.insight1,
            last_viewed_at=timezone.now(),
        )

        InsightViewed.objects.create(
            team=self.team,
            user=self.user,
            insight=self.insight2,
            last_viewed_at=timezone.now(),
        )

    def _insight_to_dict(self, insight: Insight) -> InsightDict:
        """Convert Insight model object to InsightDict."""
        return InsightDict(
            id=insight.id,
            name=insight.name,
            description=insight.description,
            query=insight.query,
            derived_name=insight.derived_name,
            short_id=insight.short_id,
        )

    async def test_load_insights_page(self):
        """Test loading paginated insights from database."""
        # Load first page
        first_page = await self.node._load_insights_page(0)

        self.assertEqual(len(first_page), 2)

        # Check that insights are loaded with correct data
        insight_ids = [insight["id"] for insight in first_page]
        self.assertIn(self.insight1.id, insight_ids)
        self.assertIn(self.insight2.id, insight_ids)

        # Check insight data structure
        insight1_data = next(i for i in first_page if i["id"] == self.insight1.id)
        self.assertEqual(insight1_data["name"], "Daily Pageviews")
        self.assertEqual(insight1_data["description"], "Track daily website traffic")

    async def test_load_insights_page_unique_only(self):
        """Test that load_insights_page returns unique insights only."""
        # Update existing insight view to simulate multiple views
        await InsightViewed.objects.filter(
            team=self.team,
            user=self.user,
            insight=self.insight1,
        ).aupdate(last_viewed_at=timezone.now())

        first_page = await self.node._load_insights_page(0)

        # Should still only have 2 unique insights
        insight_ids = [insight["id"] for insight in first_page]
        self.assertEqual(len(insight_ids), len(set(insight_ids)), "Should return unique insights only")

    async def test_format_insights_page(self):
        """Test formatting a page of insights."""
        # Test first page (automatically loads page 0)
        result = await self.node._format_insights_page(0)

        self.assertIn(f"ID: {self.insight1.id}", result)
        self.assertIn(f"ID: {self.insight2.id}", result)
        self.assertIn("Daily Pageviews", result)
        self.assertIn("User Signup Funnel", result)
        self.assertIn("Track daily website traffic", result)
        self.assertIn("Track user conversion through signup", result)

    async def test_format_insights_page_empty(self):
        """Test formatting an empty page."""
        # Test page beyond available insights
        result = await self.node._format_insights_page(10)

        self.assertEqual(result, "No insights available on this page.")

    async def test_parse_insight_ids(self):
        """Test parsing insight IDs from LLM response."""
        # Load first page to populate the IDs
        await self.node._load_insights_page(0)

        # Test response with valid IDs
        response = f"Here are the relevant insights: {self.insight1.id}, {self.insight2.id}, and 99999"

        result = self.node._parse_insight_ids(response)

        # Should return only valid IDs
        self.assertEqual(len(result), 2)
        self.assertIn(self.insight1.id, result)
        self.assertIn(self.insight2.id, result)
        self.assertNotIn(99999, result)  # Invalid ID should be filtered out

    async def test_parse_insight_ids_no_valid_ids(self):
        """Test parsing when no valid IDs are found."""
        # Load first page to populate the IDs
        await self.node._load_insights_page(0)

        response = "Here are some numbers: 99999, 88888, but no valid insight IDs"

        result = self.node._parse_insight_ids(response)

        self.assertEqual(result, [])

    def test_create_error_response(self):
        """Test creating error response."""
        result = self.node._create_error_response("Test error", "test_tool_call_id")

        self.assertIsInstance(result, PartialAssistantState)
        self.assertEqual(len(result.messages), 1)
        message = result.messages[0]
        assert isinstance(message, AssistantToolCallMessage)
        self.assertEqual(message.content, "Test error")
        self.assertEqual(message.tool_call_id, "test_tool_call_id")
        self.assertIsNone(result.search_insights_query)
        self.assertIsNone(result.root_tool_call_id)

    async def test_evaluation_flow_creates_visualization_messages(self):
        """Test that evaluation flow creates visualization messages for existing insights."""
        # Test the specific part of the arun method that handles evaluation results
        selected_insights = [self.insight1.id, self.insight2.id]
        search_query = "test query"
        insight_plan = "test plan"

        # Mock the _evaluate_insights_with_tools method to return positive result
        with patch.object(self.node, "_evaluate_insights_with_tools") as mock_evaluate:
            mock_evaluate.return_value = {
                "should_use_existing": True,
                "selected_insights": [self.insight1.id],  # Now only selects one insight by default
                "explanation": "Found 1 relevant insight:\n- Daily Pageviews: This insight is perfect for your needs.",
                "visualization_messages": [],
            }

            # Mock _search_insights_iteratively to return our test insights
            with patch.object(self.node, "_search_insights_iteratively") as mock_search:
                with patch.object(self.node, "_get_total_insights_count") as mock_count:
                    with patch.object(self.node, "_load_insights_page") as mock_load_page:
                        # Create a proper async mock
                        async def mock_search_async(query):
                            return selected_insights

                        mock_search.side_effect = mock_search_async
                        mock_count.return_value = 2  # Simulate that we have insights
                        # Mock the insights page data
                        mock_load_page.return_value = [
                            {"insight_id": self.insight1.id, "insight__name": "Daily Pageviews"},
                            {"insight_id": self.insight2.id, "insight__name": "User Signup Funnel"},
                        ]

                        # Set up state for evaluation flow (both search_query and insight_plan trigger evaluation)
                        state = AssistantState(
                            messages=[HumanMessage(content="test message")],
                            search_insights_query=search_query,
                            root_tool_insight_plan=insight_plan,
                            root_tool_call_id="test_call_id",
                        )

                        from langchain_core.runnables import RunnableConfig

                        config: RunnableConfig = {"configurable": {"thread_id": "test_thread"}}
                        result = await self.node.arun(state, config)

                        if result is None:
                            self.fail("arun() returned None")

                        # Verify that we get at least one message with the evaluation explanation
                        self.assertGreaterEqual(len(result.messages), 1, "Expected at least one message")

                        # First message should be the evaluation explanation
                        first_message = result.messages[0]
                        assert isinstance(first_message, AssistantToolCallMessage)
                        self.assertIn("Evaluation Result", first_message.content)
                        self.assertIn("Found 1 relevant insight", first_message.content)
                        self.assertIn("Daily Pageviews: This insight is perfect for your needs.", first_message.content)

                # Note: Additional visualization messages depend on query type support in test data

    @patch("ee.hogai.graph.insights.nodes.ChatOpenAI")
    def test_search_insights_iteratively_single_page(self, mock_openai):
        """Test iterative search with single page (no pagination)."""

        async def async_test():
            # Mock LLM response with insight IDs
            mock_response = MagicMock()
            mock_response.content = (
                f"Based on your query, I recommend these insights: {self.insight1.id}, {self.insight2.id}"
            )
            mock_response.tool_calls = None
            mock_openai.return_value.ainvoke = AsyncMock(return_value=mock_response)

            # Mock the sync database calls
            with patch.object(self.node, "_get_total_insights_count", return_value=2):
                with patch.object(self.node, "_format_insights_page", return_value="Mocked page"):
                    with patch.object(self.node, "_load_insights_page", return_value=[self.insight1, self.insight2]):
                        # Also mock the parse method to return the IDs from the LLM response
                        with patch.object(
                            self.node, "_parse_insight_ids", return_value=[self.insight1.id, self.insight2.id]
                        ):
                            result = await self.node._search_insights_iteratively("pageview analysis")

            return result

        result = asyncio.run(async_test())
        self.assertEqual(len(result), 2)
        self.assertIn(self.insight1.id, result)
        self.assertIn(self.insight2.id, result)

    @patch("ee.hogai.graph.insights.nodes.ChatOpenAI")
    def test_search_insights_iteratively_with_pagination(self, mock_openai):
        """Test iterative search with pagination returns valid IDs."""

        async def async_test():
            # Use existing insights from setUp
            existing_insight_ids = [self.insight1.id, self.insight2.id]
            # Mock final response with existing insight IDs
            mock_final_response = MagicMock()
            mock_final_response.content = f"Here are the insights: {existing_insight_ids[0]}, {existing_insight_ids[1]}"
            mock_final_response.tool_calls = None

            mock_openai.return_value.ainvoke = AsyncMock(return_value=mock_final_response)

            # Mock the sync database calls
            with patch.object(self.node, "_get_total_insights_count", return_value=2):
                with patch.object(self.node, "_format_insights_page", return_value="Mocked page"):
                    with patch.object(self.node, "_load_insights_page", return_value=[self.insight1, self.insight2]):
                        with patch.object(self.node, "_parse_insight_ids", return_value=existing_insight_ids):
                            result = await self.node._search_insights_iteratively("test query")

            return result

        result = asyncio.run(async_test())
        # Use existing insights from setUp
        existing_insight_ids = [self.insight1.id, self.insight2.id]
        self.assertEqual(len(result), 2)
        self.assertIn(existing_insight_ids[0], result)
        self.assertIn(existing_insight_ids[1], result)

    @patch("ee.hogai.graph.insights.nodes.ChatOpenAI")
    def test_search_insights_iteratively_fallback(self, mock_openai):
        """Test iterative search when LLM fails - should return empty list."""

        async def async_test():
            # Mock LLM to raise an exception
            mock_openai.return_value.ainvoke = AsyncMock(side_effect=Exception("LLM failed"))

            # Mock the sync database calls to avoid async issues
            with patch.object(self.node, "_get_total_insights_count", return_value=0):
                with patch.object(self.node, "_format_insights_page", return_value=""):
                    result = await self.node._search_insights_iteratively("test query")

            return result

        result = asyncio.run(async_test())
        # Should return empty list when LLM fails to select anything
        self.assertEqual(len(result), 0)

    async def test_evaluation_flow_returns_creation_when_no_suitable_insights(self):
        """Test that when evaluation returns NO, the system transitions to creation flow."""
        selected_insights = [self.insight1.id, self.insight2.id]
        search_query = "test query"
        insight_plan = "test plan"

        # Mock the _evaluate_insights_with_tools method to return NO result
        with patch.object(self.node, "_evaluate_insights_with_tools") as mock_evaluate:
            mock_evaluate.return_value = {
                "should_use_existing": False,  # This should trigger creation flow
                "selected_insights": [],
                "explanation": "These insights don't match your requirements.",
                "visualization_messages": [],
            }

            # Mock _search_insights_iteratively to return our test insights
            with patch.object(self.node, "_search_insights_iteratively") as mock_search:
                with patch.object(self.node, "_get_total_insights_count") as mock_count:
                    with patch.object(self.node, "_load_insights_page") as mock_load_page:
                        # Create a proper async mock
                        async def mock_search_async(query):
                            return selected_insights

                        mock_search.side_effect = mock_search_async
                        mock_count.return_value = 2  # Simulate that we have insights
                        # Mock the insights page data
                        mock_load_page.return_value = [
                            {"insight_id": self.insight1.id, "insight__name": "Daily Pageviews"},
                            {"insight_id": self.insight2.id, "insight__name": "User Signup Funnel"},
                        ]

                        # Set up state for evaluation flow (both search_query and insight_plan trigger evaluation)
                        state = AssistantState(
                            messages=[HumanMessage(content="test message")],
                            search_insights_query=search_query,
                            root_tool_insight_plan=insight_plan,
                            root_tool_call_id="test_call_id",
                        )

                        from langchain_core.runnables import RunnableConfig

                        config: RunnableConfig = {"configurable": {"thread_id": "test_thread"}}
                        result = await self.node.arun(state, config)

                        # Verify that search_insights_query is cleared and root_tool_insight_plan is set to search_query
                        assert result is not None
                        assert isinstance(result, PartialAssistantState)
                        self.assertIsNone(result.search_insights_query, "search_insights_query should be cleared")
                        # root_tool_insight_plan should be set to search_query to trigger creation
                        self.assertEqual(
                            result.root_tool_insight_plan,
                            search_query,
                            "root_tool_insight_plan should be set to search_query",
                        )

                        # Verify that _evaluate_insights_with_tools was called with the search_query
                        mock_evaluate.assert_called_once_with(selected_insights, search_query, max_selections=1)

    async def test_evaluation_always_called_with_search_query(self):
        """Test that evaluation is always called with search_query in current implementation."""
        selected_insights = [self.insight1.id, self.insight2.id]
        search_query = "test query"

        # Mock the search and evaluation methods
        with patch.object(self.node, "_search_insights_iteratively") as mock_search:
            with patch.object(self.node, "_get_total_insights_count") as mock_count:
                with patch.object(self.node, "_evaluate_insights_with_tools") as mock_evaluate:
                    with patch.object(self.node, "_load_insights_page") as mock_load_page:
                        # Create a proper async mock
                        async def mock_search_async(query):
                            return selected_insights

                        mock_search.side_effect = mock_search_async
                        mock_count.return_value = 1  # Simulate that we have insights
                        # Mock the insights page data
                        mock_load_page.return_value = [{"insight_id": self.insight1.id}]

                        # Mock evaluation to return "use existing"
                        mock_evaluate.return_value = {
                            "should_use_existing": True,
                            "selected_insights": [self.insight1.id],
                            "explanation": "Found 1 relevant insight:\n- Daily Pageviews: Found matching insights",
                            "visualization_messages": [],
                        }

                        # Set up state with search_query
                        state = AssistantState(
                            messages=[HumanMessage(content="find insights")],
                            search_insights_query=search_query,
                            root_tool_call_id="test_call_id",
                        )

                        from langchain_core.runnables import RunnableConfig

                        config: RunnableConfig = {"configurable": {"thread_id": "test_thread"}}
                        result = await self.node.arun(state, config)

                        # Verify that evaluation was called with search_query (current implementation behavior)
                        mock_evaluate.assert_called_once_with(selected_insights, search_query, max_selections=1)

                        # Verify that we get the evaluation response
                        assert result is not None
                        assert isinstance(result, PartialAssistantState)
                        self.assertGreaterEqual(len(result.messages), 1)

                        # Verify state cleanup
                        self.assertIsNone(result.search_insights_query)
                        self.assertIsNone(result.root_tool_call_id)

    def test_run_with_no_insights(self):
        """Test arun method when no insights exist - should raise NoInsightsException."""
        # Clear all insights (done outside async context)
        InsightViewed.objects.all().delete()
        Insight.objects.all().delete()

        conversation = Conversation.objects.create(team=self.team, user=self.user)

        state = AssistantState(
            messages=[HumanMessage(content="Find insights")],
            search_insights_query="test",
            root_tool_call_id="test_tool_call_id",
        )

        async def async_test():
            # Mock the database calls that happen in async context
            with patch.object(self.node, "_get_total_insights_count", return_value=0):
                await self.node.arun(state, {"configurable": {"thread_id": str(conversation.id)}})

        with self.assertRaises(NoInsightsException):
            asyncio.run(async_test())

    async def test_team_filtering(self):
        """Test that insights are filtered by team."""
        # Create insight for different team
        other_team = await self.organization.teams.acreate()
        other_insight = await Insight.objects.acreate(
            team=other_team,
            name="Other Team Insight",
            query={
                "source": {
                    "kind": "TrendsQuery",
                    "series": [{"event": "other_event", "kind": "EventsNode"}],
                    "dateRange": {"date_from": "-7d"},
                }
            },
            created_by=self.user,
        )
        await InsightViewed.objects.acreate(
            team=other_team,
            user=self.user,
            insight=other_insight,
            last_viewed_at=timezone.now(),
        )

        # Load first page to test team filtering
        first_page = await self.node._load_insights_page(0)

        # Should only load insights from self.team
        insight_ids = [insight["id"] for insight in first_page]
        self.assertIn(self.insight1.id, insight_ids)
        self.assertIn(self.insight2.id, insight_ids)
        self.assertNotIn(other_insight.id, insight_ids)

    async def test_create_read_insights_tool(self):
        """Test creating the read insights tool."""
        # The tool will load pages on demand, no need to pre-load
        tool = self.node._create_page_reader_tool()

        # Test the tool function
        result = await tool.ainvoke({"page_number": 0})

        self.assertIn("Page 1 insights:", result)
        self.assertIn(f"ID: {self.insight1.id}", result)
        self.assertIn("Daily Pageviews", result)

    async def test_read_insights_tool_empty_page(self):
        """Test read insights tool with empty page."""
        # The tool will load pages on demand, no need to pre-load
        tool = self.node._create_page_reader_tool()

        # Test beyond available pages
        result = await tool.ainvoke({"page_number": 10})

        self.assertEqual(result, "No more insights available.")

    async def test_evaluation_tools_select_insight(self):
        """Test the select_insight tool function."""
        # Load insights first
        await self.node._load_insights_page(0)

        # Get the tools
        tools = self.node._create_insight_evaluation_tools()
        select_insight_tool = next(t for t in tools if t.name == "select_insight")

        # Test selecting a valid insight
        result = select_insight_tool.invoke(
            {"insight_id": self.insight1.id, "explanation": "Perfect match for pageviews"}
        )

        self.assertIn(f"Selected insight {self.insight1.id}", result)
        self.assertIn("Daily Pageviews", result)
        self.assertEqual(len(self.node._evaluation_selections), 1)
        self.assertIn(self.insight1.id, self.node._evaluation_selections)
        self.assertEqual(
            self.node._evaluation_selections[self.insight1.id]["explanation"], "Perfect match for pageviews"
        )

    def test_evaluation_tools_select_invalid_insight(self):
        """Test the select_insight tool with invalid insight ID."""
        tools = self.node._create_insight_evaluation_tools()
        select_insight_tool = next(t for t in tools if t.name == "select_insight")

        result = select_insight_tool.invoke({"insight_id": 99999, "explanation": "Test"})

        self.assertEqual(result, "Insight 99999 not found")
        self.assertEqual(len(self.node._evaluation_selections), 0)

    def test_evaluation_tools_only_has_select_and_reject(self):
        """Test that evaluation tools only include select_insight and reject_all_insights."""
        # Get the tools
        tools = self.node._create_insight_evaluation_tools()

        tool_names = [tool.name for tool in tools]
        self.assertIn("select_insight", tool_names)
        self.assertIn("reject_all_insights", tool_names)
        self.assertEqual(len(tools), 2)  # Only these two tools should exist

    def test_evaluation_tools_reject_all_insights(self):
        """Test the reject_all_insights tool function."""
        # Set up some selections first
        self.node._evaluation_selections = {self.insight1.id: {"insight": {}, "explanation": "test"}}

        tools = self.node._create_insight_evaluation_tools()
        reject_tool = next(t for t in tools if t.name == "reject_all_insights")

        result = reject_tool.invoke({"reason": "None of these match the user's needs"})

        self.assertEqual(result, "All insights rejected. Will create new insight.")
        self.assertEqual(len(self.node._evaluation_selections), 0)
        self.assertEqual(self.node._rejection_reason, "None of these match the user's needs")

    @patch("ee.hogai.graph.insights.nodes.ChatOpenAI")
    async def test_evaluate_insights_with_tools_selection(self, mock_openai):
        """Test the new tool-based evaluation with insight selection."""
        # Load insights
        await self.node._load_insights_page(0)

        # Mock LLM response with tool calls
        mock_tool_response = MagicMock()
        mock_tool_response.tool_calls = [
            {
                "name": "select_insight",
                "args": {"insight_id": self.insight1.id, "explanation": "Matches pageview tracking needs"},
                "id": "call_1",
            },
            {
                "name": "select_insight",
                "args": {"insight_id": self.insight2.id, "explanation": "Also relevant for conversion tracking"},
                "id": "call_2",
            },
        ]

        mock_final_response = MagicMock()
        mock_final_response.tool_calls = None

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=[mock_tool_response, mock_final_response])
        mock_openai.return_value.bind_tools.return_value = mock_llm

        result = await self.node._evaluate_insights_with_tools(
            [self.insight1.id, self.insight2.id], "track pageviews and conversions"
        )

        self.assertTrue(result["should_use_existing"])
        self.assertEqual(len(result["selected_insights"]), 2)
        self.assertIn(self.insight1.id, result["selected_insights"])
        self.assertIn(self.insight2.id, result["selected_insights"])
        self.assertIn("Found 2 relevant insights", result["explanation"])

    async def test_create_enhanced_insight_summary(self):
        """Test the enhanced insight summary with metadata."""
        # Load insights first
        await self.node._load_insights_page(0)

        # Get the insight dict from loaded pages
        insight_dict = self.node._find_insight_by_id(self.insight1.id)

        # Test enhanced summary for a valid insight
        assert insight_dict is not None
        summary = await self.node._create_enhanced_insight_summary(insight_dict)

        self.assertIn(f"ID: {self.insight1.id}", summary)
        self.assertIn("Daily Pageviews", summary)
        self.assertIn("Type: TrendsQuery", summary)  # Should detect TrendsQuery type from query
        # Check that query result is not an error (would contain "Query type not supported")
        self.assertIn("Description: Track daily website traffic", summary)

    def test_get_basic_query_info(self):
        """Test extracting basic query information."""
        # Test basic query info extraction using the new method
        query_source = {
            "kind": "TrendsQuery",
            "series": [{"event": "$pageview", "kind": "EventsNode"}],
            "dateRange": {"date_from": "-7d"},
        }

        query_info = self.node._extract_query_metadata(query_source)

        assert query_info is not None
        self.assertIn("Events:", query_info)
        self.assertIn("$pageview", query_info)
        self.assertIn("Period:", query_info)

        # Test with empty query source
        query_info_empty = self.node._extract_query_metadata({})
        self.assertIsNone(query_info_empty)

    @patch("ee.hogai.graph.insights.nodes.ChatOpenAI")
    async def test_non_executable_insights_handling(self, mock_openai):
        """Test that non-executable insights are presented to LLM but rejected."""
        # Create a mock insight that can't be visualized
        mock_insight: InsightDict = InsightDict(
            id=99999,
            name="Broken Insight",
            description="This insight cannot be executed",
            query=None,
            derived_name=None,
            short_id="mock_short_id",
        )

        # Mock _find_insight_by_id to return our mock insight
        original_find = self.node._find_insight_by_id

        def mock_find(insight_id):
            if insight_id == 99999:
                return mock_insight
            return original_find(insight_id)

        with patch.object(self.node, "_find_insight_by_id", side_effect=mock_find):
            # Should reject
            mock_response = MagicMock()
            mock_response.tool_calls = [
                {
                    "name": "reject_all_insights",
                    "args": {"reason": "This insight cannot be executed due to missing query/filters"},
                    "id": "call_1",
                }
            ]

            mock_llm = MagicMock()
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)
            mock_openai.return_value.bind_tools.return_value = mock_llm

            # Test evaluation with non-executable insight
            result = await self.node._evaluate_insights_with_tools([99999], "test query", max_selections=1)

            # Should return no insights found (LLM should reject non-executable insights)
            self.assertFalse(result["should_use_existing"])
            self.assertEqual(len(result["selected_insights"]), 0)
            # The explanation should indicate why the insight was rejected
            self.assertTrue(len(result["explanation"]) > 0)

    @patch("ee.hogai.graph.insights.nodes.ChatOpenAI")
    async def test_evaluate_insights_with_tools_rejection(self, mock_openai):
        """Test the new tool-based evaluation with rejection."""
        # Load insights
        await self.node._load_insights_page(0)

        # Mock LLM response with rejection tool call
        mock_response = MagicMock()
        mock_response.tool_calls = [
            {
                "name": "reject_all_insights",
                "args": {"reason": "User is looking for retention analysis, but these are trends and funnels"},
                "id": "call_1",
            }
        ]

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_openai.return_value.bind_tools.return_value = mock_llm

        result = await self.node._evaluate_insights_with_tools(
            [self.insight1.id, self.insight2.id], "retention analysis"
        )

        self.assertFalse(result["should_use_existing"])
        self.assertEqual(len(result["selected_insights"]), 0)
        self.assertEqual(
            result["explanation"], "User is looking for retention analysis, but these are trends and funnels"
        )

    @patch("ee.hogai.graph.insights.nodes.ChatOpenAI")
    async def test_evaluate_insights_with_tools_multiple_selection(self, mock_openai):
        """Test the evaluation with multiple selection mode."""
        # Load insights
        await self.node._load_insights_page(0)

        # Mock LLM response with multiple tool calls
        mock_tool_response = MagicMock()
        mock_tool_response.tool_calls = [
            {
                "name": "select_insight",
                "args": {"insight_id": self.insight1.id, "explanation": "Best match for pageview tracking"},
                "id": "call_1",
            },
            {
                "name": "select_insight",
                "args": {"insight_id": self.insight2.id, "explanation": "Also useful for conversion tracking"},
                "id": "call_2",
            },
        ]

        mock_final_response = MagicMock()
        mock_final_response.tool_calls = None

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=[mock_tool_response, mock_final_response])
        mock_openai.return_value.bind_tools.return_value = mock_llm

        # Test with max_selections=2
        result = await self.node._evaluate_insights_with_tools(
            [self.insight1.id, self.insight2.id], "track pageviews and conversions", max_selections=2
        )

        self.assertTrue(result["should_use_existing"])
        self.assertEqual(len(result["selected_insights"]), 2)
        self.assertIn(self.insight1.id, result["selected_insights"])
        self.assertIn(self.insight2.id, result["selected_insights"])
        self.assertIn("Found 2 relevant insights", result["explanation"])

    async def test_returns_visualization_message_with_trends_query(self):
        """Test that VisualizationMessage answer field contains TrendsQuery."""

        # Load insights first
        await self.node._load_insights_page(0)

        # Test the full query processing
        query_obj1, _ = await self.node._process_insight_query(self._insight_to_dict(self.insight1))
        self.assertIsNotNone(query_obj1, f"Query object should not be None for insight1. Query: {self.insight1.query}")
        self.assertIsInstance(query_obj1, TrendsQuery)

        # Test insight1 visualization message creation
        viz_message1 = await self.node._create_visualization_message_for_insight(self._insight_to_dict(self.insight1))
        assert isinstance(viz_message1, VisualizationMessage), "Should create visualization message for insight1"
        assert hasattr(viz_message1, "answer"), "VisualizationMessage should have answer attribute"

        # Verify the answer contains the correct query type
        answer1 = viz_message1.answer
        self.assertIsInstance(answer1, TrendsQuery)

    async def test_returns_visualization_message_with_funnels_query(self):
        """Test that VisualizationMessage answer field contains FunnelsQuery."""

        # Load insights first
        await self.node._load_insights_page(0)

        query_obj2, _ = await self.node._process_insight_query(self._insight_to_dict(self.insight2))
        self.assertIsNotNone(query_obj2, f"Query object should not be None for insight2. Query: {self.insight2.query}")
        self.assertIsInstance(query_obj2, FunnelsQuery)

        # Test insight2 visualization message creation
        viz_message2 = await self.node._create_visualization_message_for_insight(self._insight_to_dict(self.insight2))
        assert isinstance(viz_message2, VisualizationMessage), "Should create visualization message for insight2"
        assert hasattr(viz_message2, "answer"), "VisualizationMessage should have answer attribute"

        # Verify the answer contains the correct query type
        answer2 = viz_message2.answer
        self.assertIsInstance(answer2, FunnelsQuery)

    async def test_returns_visualization_message_with_retention_query(self):
        """Test that VisualizationMessage answer field contains RetentionQuery."""
        query = InsightVizNode(
            source=RetentionQuery(
                retentionFilter=RetentionFilter(
                    targetEntity=RetentionEntity(id="$pageview", type=EntityType.EVENTS),
                    returningEntity=RetentionEntity(id="$pageview", type=EntityType.EVENTS),
                )
            )
        )
        insight = await Insight.objects.acreate(
            team=self.team,
            name="Retention Query",
            description="Retention Query",
            query=query.model_dump(),
            filters={},
            created_by=self.user,
        )
        await InsightViewed.objects.acreate(
            team=self.team,
            user=self.user,
            insight=insight,
            last_viewed_at=timezone.now() - timedelta(days=1),
        )

        await self.node._load_insights_page(0)

        insight_dict = self._insight_to_dict(insight)
        query_obj, _ = await self.node._process_insight_query(insight_dict)
        self.assertIsNotNone(query_obj, f"Query object should not be None for insight. Query: {insight_dict['query']}")
        self.assertIsInstance(query_obj, RetentionQuery)

        # Test insight visualization message creation
        viz_message = await self.node._create_visualization_message_for_insight(insight_dict)
        assert isinstance(viz_message, VisualizationMessage), "Should create visualization message for insight"
        assert hasattr(viz_message, "answer"), "VisualizationMessage should have answer attribute"

        # Verify the answer contains the correct query type
        answer = viz_message.answer
        self.assertIsInstance(answer, RetentionQuery)

    async def test_returns_visualization_message_with_hogql_query(self):
        """Test that VisualizationMessage answer field contains HogQLQuery."""
        query = DataTableNode(source=HogQLQuery(query="SELECT 1"))
        insight = await Insight.objects.acreate(
            team=self.team,
            name="HogQL Query",
            description="HogQL Query",
            query=query.model_dump(),
            filters={},
            created_by=self.user,
        )
        await InsightViewed.objects.acreate(
            team=self.team,
            user=self.user,
            insight=insight,
            last_viewed_at=timezone.now(),
        )

        await self.node._load_insights_page(0)

        insight_dict = self._insight_to_dict(insight)
        query_obj, _ = await self.node._process_insight_query(insight_dict)
        self.assertIsNotNone(query_obj, f"Query object should not be None for insight. Query: {insight_dict['query']}")
        self.assertIsInstance(query_obj, HogQLQuery)

        # Test insight visualization message creation
        viz_message = await self.node._create_visualization_message_for_insight(insight_dict)
        assert isinstance(viz_message, VisualizationMessage), "Should create visualization message for insight"
        assert hasattr(viz_message, "answer"), "VisualizationMessage should have answer attribute"

        # Verify the answer contains the correct query type
        answer = viz_message.answer
        self.assertIsInstance(answer, HogQLQuery)
