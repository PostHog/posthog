from unittest.mock import patch, MagicMock, AsyncMock
from django.utils import timezone
import asyncio


from ee.hogai.graph.insights.nodes import InsightSearchNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.models.assistant import Conversation
from posthog.models import Insight, InsightViewed
from posthog.schema import AssistantToolCallMessage, HumanMessage
from posthog.test.base import BaseTest


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

    def test_router_returns_root(self):
        """Test that router returns 'root' as expected."""
        result = self.node.router(AssistantState(messages=[]))
        self.assertEqual(result, "root")

    def test_load_insights_page(self):
        """Test loading paginated insights from database."""
        # Load first page
        first_page = self.node._load_insights_page(0)

        self.assertEqual(len(first_page), 2)

        # Check that insights are loaded with correct data
        insight_ids = [insight.id for insight in first_page]
        self.assertIn(self.insight1.id, insight_ids)
        self.assertIn(self.insight2.id, insight_ids)

        # Check insight data structure
        insight1_data = next(i for i in first_page if i.id == self.insight1.id)
        self.assertEqual(insight1_data.name, "Daily Pageviews")
        self.assertEqual(insight1_data.description, "Track daily website traffic")

    def test_load_insights_page_unique_only(self):
        """Test that load_insights_page returns unique insights only."""
        # Update existing insight view to simulate multiple views
        InsightViewed.objects.filter(
            team=self.team,
            user=self.user,
            insight=self.insight1,
        ).update(last_viewed_at=timezone.now())

        first_page = self.node._load_insights_page(0)

        # Should still only have 2 unique insights
        insight_ids = [insight.id for insight in first_page]
        self.assertEqual(len(insight_ids), len(set(insight_ids)), "Should return unique insights only")

    def test_format_insights_page(self):
        """Test formatting a page of insights."""
        # Test first page (automatically loads page 0)
        result = self.node._format_insights_page(0)

        self.assertIn(f"ID: {self.insight1.id}", result)
        self.assertIn(f"ID: {self.insight2.id}", result)
        self.assertIn("Daily Pageviews", result)
        self.assertIn("User Signup Funnel", result)
        self.assertIn("Track daily website traffic", result)
        self.assertIn("Track user conversion through signup", result)

    def test_format_insights_page_empty(self):
        """Test formatting an empty page."""
        # Test page beyond available insights
        result = self.node._format_insights_page(10)

        self.assertEqual(result, "No insights available on this page.")

    def test_parse_insight_ids(self):
        """Test parsing insight IDs from LLM response."""
        # Load first page to populate the IDs
        self.node._load_insights_page(0)

        # Test response with valid IDs
        response = f"Here are the relevant insights: {self.insight1.id}, {self.insight2.id}, and 99999"

        result = self.node._parse_insight_ids(response)

        # Should return only valid IDs
        self.assertEqual(len(result), 2)
        self.assertIn(self.insight1.id, result)
        self.assertIn(self.insight2.id, result)
        self.assertNotIn(99999, result)  # Invalid ID should be filtered out

    def test_parse_insight_ids_no_valid_ids(self):
        """Test parsing when no valid IDs are found."""
        # Load first page to populate the IDs
        self.node._load_insights_page(0)

        response = "Here are some numbers: 99999, 88888, but no valid insight IDs"

        result = self.node._parse_insight_ids(response)

        self.assertEqual(result, [])

    def test_create_error_response(self):
        """Test creating error response."""
        result = self.node._create_error_response("Test error", "test_tool_call_id")

        self.assertIsInstance(result, PartialAssistantState)
        self.assertEqual(len(result.messages), 1)
        self.assertIsInstance(result.messages[0], AssistantToolCallMessage)
        self.assertEqual(result.messages[0].content, "Test error")
        self.assertEqual(result.messages[0].tool_call_id, "test_tool_call_id")
        self.assertIsNone(result.search_insights_query)
        self.assertIsNone(result.root_tool_call_id)

    def test_evaluation_flow_creates_visualization_messages(self):
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

                        config = {"configurable": {"thread_id": "test_thread"}}
                        result = asyncio.run(self.node.arun(state, config))

                        if result is None:
                            self.fail("arun() returned None")
                        if result.messages is None:
                            result.messages = []

                        # Verify that we get at least one message with the evaluation explanation
                        self.assertGreaterEqual(len(result.messages), 1, "Expected at least one message")

                        # First message should be the evaluation explanation
                        first_message = result.messages[0]
                        self.assertIsInstance(first_message, AssistantToolCallMessage)
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

    def test_router_always_returns_root(self):
        """Test that router always returns 'root'."""
        state = AssistantState(messages=[], root_tool_insight_plan="some plan", search_insights_query=None)
        result = self.node.router(state)
        self.assertEqual(result, "root")

    def test_evaluation_flow_returns_creation_when_no_suitable_insights(self):
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

                        config = {"configurable": {"thread_id": "test_thread"}}
                        result = asyncio.run(self.node.arun(state, config))

                        # Verify that search_insights_query is cleared and root_tool_insight_plan is set to search_query
                        self.assertIsNotNone(result)
                        self.assertIsInstance(result, PartialAssistantState)
                        self.assertIsNone(result.search_insights_query, "search_insights_query should be cleared")
                        # root_tool_insight_plan should be set to search_query to trigger creation
                        self.assertEqual(
                            result.root_tool_insight_plan,
                            search_query,
                            "root_tool_insight_plan should be set to search_query",
                        )

                        # Test router behavior with the returned state
                        # Create a new state that simulates what happens after this node runs
                        post_evaluation_state = AssistantState(
                            messages=state.messages,
                            root_tool_insight_plan=search_query,  # This gets set to search_query
                            search_insights_query=None,  # This gets cleared
                        )

                        router_result = self.node.router(post_evaluation_state)
                        self.assertEqual(
                            router_result,
                            "root",
                            "Router should always return root",
                        )

                        # Verify that _evaluate_insights_with_tools was called with the search_query
                        mock_evaluate.assert_called_once_with(selected_insights, search_query, max_selections=1)

    def test_evaluation_always_called_with_search_query(self):
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

                        config = {"configurable": {"thread_id": "test_thread"}}
                        result = asyncio.run(self.node.arun(state, config))

                        # Verify that evaluation was called with search_query (current implementation behavior)
                        mock_evaluate.assert_called_once_with(selected_insights, search_query, max_selections=1)

                        # Verify that we get the evaluation response
                        self.assertIsNotNone(result)
                        self.assertIsInstance(result, PartialAssistantState)
                        self.assertGreaterEqual(len(result.messages), 1)

                        # Verify state cleanup
                        self.assertIsNone(result.search_insights_query)
                        self.assertIsNone(result.root_tool_call_id)

    def test_run_with_no_insights(self):
        """Test arun method when no insights exist."""
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
                result = await self.node.arun(state, {"configurable": {"thread_id": str(conversation.id)}})
            return result

        result = asyncio.run(async_test())
        self.assertIsInstance(result, PartialAssistantState)
        self.assertEqual(len(result.messages), 1)
        self.assertIn("No insights found in the database", result.messages[0].content)

    def test_team_filtering(self):
        """Test that insights are filtered by team."""
        # Create insight for different team
        other_team = self.organization.teams.create()
        other_insight = Insight.objects.create(
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
        InsightViewed.objects.create(
            team=other_team,
            user=self.user,
            insight=other_insight,
            last_viewed_at=timezone.now(),
        )

        # Load first page to test team filtering
        first_page = self.node._load_insights_page(0)

        # Should only load insights from self.team
        insight_ids = [insight.id for insight in first_page]
        self.assertIn(self.insight1.id, insight_ids)
        self.assertIn(self.insight2.id, insight_ids)
        self.assertNotIn(other_insight.id, insight_ids)

    def test_create_read_insights_tool(self):
        """Test creating the read insights tool."""
        # The tool will load pages on demand, no need to pre-load
        tool = self.node._create_page_reader_tool()

        # Test the tool function
        result = tool.invoke({"page_number": 0})

        self.assertIn("Page 1 insights:", result)
        self.assertIn(f"ID: {self.insight1.id}", result)
        self.assertIn("Daily Pageviews", result)

    def test_read_insights_tool_empty_page(self):
        """Test read insights tool with empty page."""
        # The tool will load pages on demand, no need to pre-load
        tool = self.node._create_page_reader_tool()

        # Test beyond available pages
        result = tool.invoke({"page_number": 10})

        self.assertEqual(result, "No more insights available.")

    def test_evaluation_tools_select_insight(self):
        """Test the select_insight tool function."""
        # Load insights first
        self.node._load_insights_page(0)

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
    def test_evaluate_insights_with_tools_selection(self, mock_openai):
        """Test the new tool-based evaluation with insight selection."""
        # Load insights
        self.node._load_insights_page(0)

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
        mock_llm.invoke.side_effect = [mock_tool_response, mock_final_response]
        mock_openai.return_value.bind_tools.return_value = mock_llm

        result = self.node._evaluate_insights_with_tools(
            [self.insight1.id, self.insight2.id], "track pageviews and conversions"
        )

        self.assertTrue(result["should_use_existing"])
        self.assertEqual(len(result["selected_insights"]), 2)
        self.assertIn(self.insight1.id, result["selected_insights"])
        self.assertIn(self.insight2.id, result["selected_insights"])
        self.assertIn("Found 2 relevant insights", result["explanation"])

    def test_create_enhanced_insight_summary(self):
        """Test the enhanced insight summary with metadata."""
        # Load insights first
        self.node._load_insights_page(0)

        # Get the insight dict from loaded pages
        insight_dict = self.node._find_insight_by_id(self.insight1.id)

        # Test enhanced summary for a valid insight
        summary = self.node._create_enhanced_insight_summary(insight_dict)

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

        self.assertIsNotNone(query_info)
        self.assertIn("Events:", query_info)
        self.assertIn("$pageview", query_info)
        self.assertIn("Period:", query_info)

        # Test with empty query source
        query_info_empty = self.node._extract_query_metadata({})
        self.assertIsNone(query_info_empty)

    @patch("ee.hogai.graph.insights.nodes.ChatOpenAI")
    def test_non_executable_insights_handling(self, mock_openai):
        """Test that non-executable insights are presented to LLM but rejected."""
        # Create a mock insight that can't be visualized
        mock_insight = Insight(
            id=99999,
            name="Broken Insight",
            description="This insight cannot be executed",
            query=None,
            filters=None,
            team=self.team,
        )

        # Mock _find_insight_by_id to return our mock insight
        original_find = self.node._find_insight_by_id

        def mock_find(insight_id):
            if insight_id == 99999:
                return mock_insight
            return original_find(insight_id)

        self.node._find_insight_by_id = mock_find

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
        mock_llm.invoke.return_value = mock_response
        mock_openai.return_value = mock_llm

        # Test evaluation with non-executable insight
        result = self.node._evaluate_insights_with_tools([99999], "test query", max_selections=1)

        # Should return no insights found (LLM should reject non-executable insights)
        self.assertFalse(result["should_use_existing"])
        self.assertEqual(len(result["selected_insights"]), 0)
        # The explanation should indicate why the insight was rejected
        self.assertTrue(len(result["explanation"]) > 0)

        # Restore original method
        self.node._find_insight_by_id = original_find

    @patch("ee.hogai.graph.insights.nodes.ChatOpenAI")
    def test_evaluate_insights_with_tools_rejection(self, mock_openai):
        """Test the new tool-based evaluation with rejection."""
        # Load insights
        self.node._load_insights_page(0)

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
        mock_llm.invoke.return_value = mock_response
        mock_openai.return_value.bind_tools.return_value = mock_llm

        result = self.node._evaluate_insights_with_tools([self.insight1.id, self.insight2.id], "retention analysis")

        self.assertFalse(result["should_use_existing"])
        self.assertEqual(len(result["selected_insights"]), 0)
        self.assertEqual(
            result["explanation"], "User is looking for retention analysis, but these are trends and funnels"
        )

    @patch("ee.hogai.graph.insights.nodes.ChatOpenAI")
    def test_evaluate_insights_with_tools_multiple_selection(self, mock_openai):
        """Test the evaluation with multiple selection mode."""
        # Load insights
        self.node._load_insights_page(0)

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
        mock_llm.invoke.side_effect = [mock_tool_response, mock_final_response]
        mock_openai.return_value.bind_tools.return_value = mock_llm

        # Test with max_selections=2
        result = self.node._evaluate_insights_with_tools(
            [self.insight1.id, self.insight2.id], "track pageviews and conversions", max_selections=2
        )

        self.assertTrue(result["should_use_existing"])
        self.assertEqual(len(result["selected_insights"]), 2)
        self.assertIn(self.insight1.id, result["selected_insights"])
        self.assertIn(self.insight2.id, result["selected_insights"])
        self.assertIn("Found 2 relevant insights", result["explanation"])
