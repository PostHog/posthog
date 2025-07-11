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
            query={"kind": "InsightVizNode", "source": {"kind": "TrendsQuery"}},
            filters={"insight": "TRENDS"},
            created_by=self.user,
        )

        self.insight2 = Insight.objects.create(
            team=self.team,
            name="User Signup Funnel",
            description="Track user conversion through signup",
            query={"kind": "InsightVizNode", "source": {"kind": "FunnelsQuery"}},
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

    def test_load_all_insights(self):
        """Test loading all insights from database."""
        self.node._load_all_insights()

        self.assertEqual(len(self.node._all_insights), 2)

        # Check that insights are loaded with correct data
        insight_ids = [insight["insight_id"] for insight in self.node._all_insights]
        self.assertIn(self.insight1.id, insight_ids)
        self.assertIn(self.insight2.id, insight_ids)

        # Check insight data structure
        insight1_data = next(i for i in self.node._all_insights if i["insight_id"] == self.insight1.id)
        self.assertEqual(insight1_data["insight__name"], "Daily Pageviews")
        self.assertEqual(insight1_data["insight__description"], "Track daily website traffic")

    def test_load_all_insights_unique_only(self):
        """Test that load_all_insights returns unique insights only."""
        # Update existing insight view to simulate multiple views
        InsightViewed.objects.filter(
            team=self.team,
            user=self.user,
            insight=self.insight1,
        ).update(last_viewed_at=timezone.now())

        self.node._load_all_insights()

        # Should still only have 2 unique insights
        insight_ids = [insight["insight_id"] for insight in self.node._all_insights]
        self.assertEqual(len(insight_ids), len(set(insight_ids)), "Should return unique insights only")

    def test_format_insights_page(self):
        """Test formatting a page of insights."""
        self.node._load_all_insights()

        # Test first page
        result = self.node._format_insights_page(0)

        self.assertIn(f"ID: {self.insight1.id}", result)
        self.assertIn(f"ID: {self.insight2.id}", result)
        self.assertIn("Daily Pageviews", result)
        self.assertIn("User Signup Funnel", result)
        self.assertIn("Track daily website traffic", result)
        self.assertIn("Track user conversion through signup", result)

    def test_format_insights_page_empty(self):
        """Test formatting an empty page."""
        self.node._load_all_insights()

        # Test page beyond available insights
        result = self.node._format_insights_page(10)

        self.assertEqual(result, "No insights available on this page.")

    def test_parse_insight_ids(self):
        """Test parsing insight IDs from LLM response."""
        self.node._load_all_insights()

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
        self.node._load_all_insights()

        response = "Here are some numbers: 99999, 88888, but no valid insight IDs"

        result = self.node._parse_insight_ids(response)

        self.assertEqual(result, [])

    def test_format_search_results_no_results(self):
        """Test formatting when no results are found."""
        result = self.node._format_search_results([], "test query")

        self.assertIn("No insights found matching 'test query'", result)
        self.assertIn("Suggest that the user try", result)

    def test_format_search_results_with_results(self):
        """Test formatting with actual results."""
        self.node._load_all_insights()

        # Use actual insight IDs
        selected_insights = [self.insight1.id, self.insight2.id]

        result = self.node._format_search_results(selected_insights, "pageviews")

        self.assertIn("Found 2 insights matching 'pageviews'", result)
        self.assertIn("**1. Daily Pageviews**", result)
        self.assertIn("**2. User Signup Funnel**", result)
        self.assertIn("Track daily website traffic", result)
        self.assertIn("Track user conversion through signup", result)
        self.assertIn("INSTRUCTIONS: Ask the user if they want to modify one of these insights", result)

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

    @patch("ee.hogai.graph.insights.nodes.ChatOpenAI")
    def test_search_insights_iteratively_single_page(self, mock_openai):
        """Test iterative search with single page (no pagination)."""
        self.node._load_all_insights()

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
                created_by=self.user,
            )
            InsightViewed.objects.create(
                team=self.team,
                user=self.user,
                insight=insight,
                last_viewed_at=timezone.now(),
            )
            insights.append(insight)

        self.node._load_all_insights()
        self.node._page_size = 20  # Force pagination

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
        self.node._load_all_insights()

        # Mock LLM to raise an exception
        mock_openai.return_value.invoke.side_effect = Exception("LLM failed")

        result = self.node._search_insights_iteratively("test query")

        # Should fallback to first 3 insights
        self.assertEqual(len(result), 2)  # We only have 2 insights in test data
        self.assertIn(self.insight1.id, result)
        self.assertIn(self.insight2.id, result)

    @patch("ee.hogai.graph.insights.nodes.ChatOpenAI")
    def test_run_with_iterative_search(self, mock_openai):
        """Test full run method with iterative search."""
        conversation = Conversation.objects.create(team=self.team, user=self.user)

        # Mock LLM response
        mock_response = MagicMock()
        mock_response.content = f"Here are relevant insights: {self.insight1.id}"
        mock_response.tool_calls = None
        mock_openai.return_value.invoke.return_value = mock_response

        state = AssistantState(
            messages=[HumanMessage(content="Find pageview insights")],
            search_insights_query="pageview insights",
            root_tool_call_id="test_tool_call_id",
        )

        result = self.node.run(state, {"configurable": {"thread_id": str(conversation.id)}})

        self.assertIsInstance(result, PartialAssistantState)
        self.assertEqual(len(result.messages), 1)
        self.assertIsInstance(result.messages[0], AssistantToolCallMessage)
        self.assertEqual(result.messages[0].tool_call_id, "test_tool_call_id")
        self.assertIn("Found", result.messages[0].content)
        self.assertIn("INSTRUCTIONS:", result.messages[0].content)
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
            created_by=self.user,
        )
        InsightViewed.objects.create(
            team=other_team,
            user=self.user,
            insight=other_insight,
            last_viewed_at=timezone.now(),
        )

        self.node._load_all_insights()

        # Should only load insights from self.team
        insight_ids = [insight["insight_id"] for insight in self.node._all_insights]
        self.assertIn(self.insight1.id, insight_ids)
        self.assertIn(self.insight2.id, insight_ids)
        self.assertNotIn(other_insight.id, insight_ids)

    def test_create_read_insights_tool(self):
        """Test creating the read insights tool."""
        self.node._load_all_insights()

        tool = self.node._create_read_insights_tool()

        # Test the tool function
        result = tool.invoke({"page_number": 0})

        self.assertIn("Page 1 insights:", result)
        self.assertIn(f"ID: {self.insight1.id}", result)
        self.assertIn("Daily Pageviews", result)

    def test_read_insights_tool_empty_page(self):
        """Test read insights tool with empty page."""
        self.node._load_all_insights()

        tool = self.node._create_read_insights_tool()

        # Test beyond available pages
        result = tool.invoke({"page_number": 10})

        self.assertEqual(result, "No more insights available.")
