from unittest.mock import patch, MagicMock
from django.utils import timezone


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
                "kind": "TrendsQuery",
                "series": [{"event": "$pageview", "kind": "EventsNode"}],
                "dateRange": {"date_from": "-7d"},
            },
            filters={"insight": "TRENDS"},
            created_by=self.user,
        )

        self.insight2 = Insight.objects.create(
            team=self.team,
            name="User Signup Funnel",
            description="Track user conversion through signup",
            query={
                "kind": "FunnelsQuery",
                "series": [
                    {"event": "signup_start", "kind": "EventsNode"},
                    {"event": "signup_complete", "kind": "EventsNode"},
                ],
                "dateRange": {"date_from": "-7d"},
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
        insight_ids = [insight["insight_id"] for insight in first_page]
        self.assertIn(self.insight1.id, insight_ids)
        self.assertIn(self.insight2.id, insight_ids)

        # Check insight data structure
        insight1_data = next(i for i in first_page if i["insight_id"] == self.insight1.id)
        self.assertEqual(insight1_data["insight__name"], "Daily Pageviews")
        self.assertEqual(insight1_data["insight__description"], "Track daily website traffic")

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
        insight_ids = [insight["insight_id"] for insight in first_page]
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
        # Test the specific part of the run method that handles evaluation results
        selected_insights = [self.insight1.id, self.insight2.id]
        search_query = "test query"
        insight_plan = "test plan"

        # Mock the _evaluate_insights_for_creation method to return positive result
        with patch.object(self.node, "_evaluate_insights_for_creation") as mock_evaluate:
            mock_evaluate.return_value = {
                "should_use_existing": True,
                "explanation": "YES: This insight is perfect for your needs.",
                "visualization_messages": [],
            }

            # Mock _search_insights_iteratively to return our test insights
            with patch.object(self.node, "_search_insights_iteratively") as mock_search:
                with patch.object(self.node, "_get_total_insights_count") as mock_count:
                    with patch.object(self.node, "_load_insights_page") as mock_load_page:
                        mock_search.return_value = selected_insights
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
                        result = self.node.run(state, config)

                        if result is None:
                            self.fail("run() returned None")
                        if result.messages is None:
                            result.messages = []

                        # Verify that we get at least one message with the evaluation explanation
                        self.assertGreaterEqual(len(result.messages), 1, "Expected at least one message")

                        # First message should be the evaluation explanation
                        first_message = result.messages[0]
                        self.assertIsInstance(first_message, AssistantToolCallMessage)
                        self.assertIn("Evaluation Result", first_message.content)
                        self.assertIn("YES: This insight is perfect for your needs.", first_message.content)

                # Note: Additional visualization messages depend on query type support in test data

    @patch("ee.hogai.graph.insights.nodes.ChatOpenAI")
    def test_search_insights_iteratively_single_page(self, mock_openai):
        """Test iterative search with single page (no pagination)."""
        # Load the first page so insights are available for search
        self.node._load_insights_page(0)

        # Mock LLM response with insight IDs
        mock_response = MagicMock()
        mock_response.content = (
            f"Based on your query, I recommend these insights: {self.insight1.id}, {self.insight2.id}"
        )
        mock_response.tool_calls = None
        mock_openai.return_value.invoke.return_value = mock_response

        result = self.node._search_insights_iteratively("pageview analysis")

        self.assertEqual(len(result), 2)
        self.assertIn(self.insight1.id, result)
        self.assertIn(self.insight2.id, result)

    @patch("ee.hogai.graph.insights.nodes.ChatOpenAI")
    def test_search_insights_iteratively_with_pagination(self, mock_openai):
        """Test iterative search with pagination (mocked large dataset)."""
        # Create many insights to trigger pagination
        insights = []
        for i in range(100):
            insight = Insight.objects.create(
                team=self.team,
                name=f"Test Insight {i}",
                description=f"Test description {i}",
                query={
                    "kind": "TrendsQuery",
                    "series": [{"event": f"test_event_{i}", "kind": "EventsNode"}],
                    "dateRange": {"date_from": "-7d"},
                },
                created_by=self.user,
            )
            InsightViewed.objects.create(
                team=self.team,
                user=self.user,
                insight=insight,
                last_viewed_at=timezone.now(),
            )
            insights.append(insight)

        # Set smaller page size to force pagination
        self.node._page_size = 20  # Force pagination
        # The insights will be loaded automatically when accessed

        # Mock tool-calling response followed by final response
        mock_tool_response = MagicMock()
        mock_tool_response.tool_calls = [
            {"name": "read_insights_page", "args": {"page_number": 1}, "id": "test_tool_call_123"}
        ]

        mock_final_response = MagicMock()
        mock_final_response.content = (
            f"I found these relevant insights: {insights[0].id}, {insights[1].id}, {insights[2].id}"
        )
        mock_final_response.tool_calls = None

        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = [mock_tool_response, mock_final_response]
        mock_openai.return_value.bind_tools.return_value = mock_llm

        result = self.node._search_insights_iteratively("test query")

        self.assertEqual(len(result), 3)
        self.assertEqual(mock_llm.invoke.call_count, 2)

    @patch("ee.hogai.graph.insights.nodes.ChatOpenAI")
    def test_search_insights_iteratively_fallback(self, mock_openai):
        """Test iterative search fallback when LLM fails."""
        # Load the first page so insights are available for fallback
        self.node._load_insights_page(0)

        # Mock LLM to raise an exception
        mock_openai.return_value.invoke.side_effect = Exception("LLM failed")

        result = self.node._search_insights_iteratively("test query")

        # Should fallback to first 3 insights
        self.assertEqual(len(result), 2)  # We only have 2 insights in test data
        self.assertIn(self.insight1.id, result)
        self.assertIn(self.insight2.id, result)

    def test_router_returns_insights(self):
        """Test that router returns 'insights' when root_tool_insight_plan is set but search_insights_query is not."""
        state = AssistantState(messages=[], root_tool_insight_plan="some plan", search_insights_query=None)
        result = self.node.router(state)
        self.assertEqual(result, "insights")

    def test_evaluation_flow_returns_creation_when_no_suitable_insights(self):
        """Test that when evaluation returns NO, the system transitions to creation flow."""
        selected_insights = [self.insight1.id, self.insight2.id]
        search_query = "test query"
        insight_plan = "test plan"

        # Mock the _evaluate_insights_for_creation method to return NO result
        with patch.object(self.node, "_evaluate_insights_for_creation") as mock_evaluate:
            mock_evaluate.return_value = {
                "should_use_existing": False,  # This should trigger creation flow
                "explanation": "NO: These insights don't match your requirements.",
                "visualization_messages": [],
            }

            # Mock _search_insights_iteratively to return our test insights
            with patch.object(self.node, "_search_insights_iteratively") as mock_search:
                with patch.object(self.node, "_get_total_insights_count") as mock_count:
                    with patch.object(self.node, "_load_insights_page") as mock_load_page:
                        mock_search.return_value = selected_insights
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
                        result = self.node.run(state, config)

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
                            "insights",
                            "Router should direct to insights creation when evaluation says NO",
                        )

                        # Verify that _evaluate_insights_for_creation was called with the search_query (current implementation)
                        mock_evaluate.assert_called_once_with(selected_insights, search_query)

    def test_evaluation_always_called_with_search_query(self):
        """Test that evaluation is always called with search_query in current implementation."""
        selected_insights = [self.insight1.id, self.insight2.id]
        search_query = "test query"

        # Mock the search and evaluation methods
        with patch.object(self.node, "_search_insights_iteratively") as mock_search:
            with patch.object(self.node, "_get_total_insights_count") as mock_count:
                with patch.object(self.node, "_evaluate_insights_for_creation") as mock_evaluate:
                    with patch.object(self.node, "_load_insights_page") as mock_load_page:
                        mock_search.return_value = selected_insights
                        mock_count.return_value = 1  # Simulate that we have insights
                        # Mock the insights page data
                        mock_load_page.return_value = [{"insight_id": self.insight1.id}]

                        # Mock evaluation to return "use existing" to avoid format_search_results call
                        mock_evaluate.return_value = {
                            "should_use_existing": True,
                            "explanation": "YES: Found matching insights",
                            "visualization_messages": [],
                        }

                        # Set up state with search_query
                        state = AssistantState(
                            messages=[HumanMessage(content="find insights")],
                            search_insights_query=search_query,
                            root_tool_call_id="test_call_id",
                        )

                        config = {"configurable": {"thread_id": "test_thread"}}
                        result = self.node.run(state, config)

                        # Verify that evaluation was called with search_query (current implementation behavior)
                        mock_evaluate.assert_called_once_with(selected_insights, search_query)

                        # Verify that we get the evaluation response
                        self.assertIsNotNone(result)
                        self.assertIsInstance(result, PartialAssistantState)
                        self.assertGreaterEqual(len(result.messages), 1)

                        # Verify state cleanup
                        self.assertIsNone(result.search_insights_query)
                        self.assertIsNone(result.root_tool_call_id)

    def test_run_with_no_insights(self):
        """Test run method when no insights exist."""
        # Clear all insights
        InsightViewed.objects.all().delete()
        Insight.objects.all().delete()

        conversation = Conversation.objects.create(team=self.team, user=self.user)

        state = AssistantState(
            messages=[HumanMessage(content="Find insights")],
            search_insights_query="test",
            root_tool_call_id="test_tool_call_id",
        )

        result = self.node.run(state, {"configurable": {"thread_id": str(conversation.id)}})

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
                "kind": "TrendsQuery",
                "series": [{"event": "other_event", "kind": "EventsNode"}],
                "dateRange": {"date_from": "-7d"},
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
        insight_ids = [insight["insight_id"] for insight in first_page]
        self.assertIn(self.insight1.id, insight_ids)
        self.assertIn(self.insight2.id, insight_ids)
        self.assertNotIn(other_insight.id, insight_ids)

    def test_create_read_insights_tool(self):
        """Test creating the read insights tool."""
        # The tool will load pages on demand, no need to pre-load
        tool = self.node._create_read_insights_tool()

        # Test the tool function
        result = tool.invoke({"page_number": 0})

        self.assertIn("Page 1 insights:", result)
        self.assertIn(f"ID: {self.insight1.id}", result)
        self.assertIn("Daily Pageviews", result)

    def test_read_insights_tool_empty_page(self):
        """Test read insights tool with empty page."""
        # The tool will load pages on demand, no need to pre-load
        tool = self.node._create_read_insights_tool()

        # Test beyond available pages
        result = tool.invoke({"page_number": 10})

        self.assertEqual(result, "No more insights available.")
