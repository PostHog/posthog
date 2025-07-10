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

    def test_search_insights_returns_unique_insights(self):
        """Test that search returns unique insights without duplicates."""
        # Create multiple views of same insight by updating existing record
        InsightViewed.objects.filter(
            team=self.team,
            user=self.user,
            insight=self.insight1,
        ).update(last_viewed_at=timezone.now())

        results, _cache_stats = self.node._search_insights()

        # Should get unique insights only
        insight_ids = [r.get("insight_id") or r.get("id") for r in results]
        self.assertEqual(len(insight_ids), len(set(insight_ids)), "Should return unique insights only")

    def test_convert_to_enriched_insights(self):
        """Test converting insights with scores to enriched format."""
        filtered_insights = [
            {
                "insight_id": self.insight1.id,
                "insight__name": "Daily Pageviews",
                "insight__description": "Track daily website traffic",
                "insight__derived_name": None,
                "insight__query": {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery"}},
                "insight__filters": {"insight": "TRENDS"},
                "insight__short_id": "abc123",
                "relevance_score": 0.9,
                "keyword_score": 0.8,
                "semantic_score": 0.9,
            },
            {
                "insight_id": self.insight2.id,
                "insight__name": "User Signup Funnel",
                "insight__description": "Track user conversion",
                "insight__derived_name": None,
                "insight__query": {"kind": "InsightVizNode", "source": {"kind": "FunnelsQuery"}},
                "insight__filters": {"insight": "FUNNELS"},
                "insight__short_id": "def456",
                "relevance_score": 0.7,
                "keyword_score": 0.6,
                "semantic_score": 0.7,
            },
        ]

        results = self.node._convert_to_enriched_insights(filtered_insights)

        self.assertEqual(len(results), 2)

        # Check first insight
        result1 = next(r for r in results if r["id"] == self.insight1.id)
        self.assertEqual(result1["name"], "Daily Pageviews")
        self.assertEqual(result1["description"], "Track daily website traffic")
        self.assertEqual(result1["relevance_score"], 0.9)
        self.assertIn("query", result1)

    def test_summarize_query_data_with_new_format(self):
        """Test query data summarization for new query format."""
        query_data = {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery"}}

        result = self.node._summarize_query_data(query_data)
        self.assertEqual(result, "TrendsQuery analysis (InsightVizNode)")

    def test_summarize_query_data_with_legacy_format(self):
        """Test query data summarization for legacy filters format."""
        query_data = {}

        result = self.node._summarize_query_data(query_data)
        self.assertEqual(result, "No query data available")

    def test_summarize_query_data_with_no_data(self):
        """Test query data summarization with no data."""
        result = self.node._summarize_query_data({})
        self.assertEqual(result, "No query data available")

    @patch("ee.hogai.graph.insights.nodes.ChatOpenAI")
    def test_semantic_filter_insights(self, mock_openai):
        """Test semantic filtering with mocked LLM."""
        # Mock structured output response for single-pass selection
        mock_structured_model = MagicMock()
        mock_structured_model.invoke.return_value = {
            "selected_insight": "Daily Pageviews",
            "confidence": 0.9,
            "reasoning": "Direct match for pageview analysis",
        }
        mock_openai.return_value.with_structured_output.return_value = mock_structured_model

        insights = [
            {
                "insight_id": self.insight1.id,
                "insight__name": "Daily Pageviews",
                "insight__description": "Track daily website traffic",
                "insight__derived_name": None,
            }
        ]

        results = self.node._semantic_filter_insights(insights, "pageview analysis")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["relevance_score"], 0.9)  # confidence score
        self.assertEqual(results[0]["semantic_score"], 0.9)
        mock_structured_model.invoke.assert_called_once()

    @patch("ee.hogai.graph.insights.nodes.ChatOpenAI")
    def test_semantic_filter_insights_fallback(self, mock_openai):
        """Test semantic filtering fallback when LLM fails."""
        # Mock LLM to raise an exception
        mock_structured_model = MagicMock()
        mock_structured_model.invoke.side_effect = Exception("LLM failed")
        mock_openai.return_value.with_structured_output.return_value = mock_structured_model

        insights = [
            {
                "insight_id": self.insight1.id,
                "insight__name": "Daily Pageviews",
                "insight__description": "Track daily website traffic",
                "insight__derived_name": None,
            }
        ]

        results = self.node._semantic_filter_insights(insights, "user signup")

        self.assertEqual(len(results), 1)  # Should return fallback insight
        self.assertEqual(results[0]["relevance_score"], 0.3)  # Fallback score

    def test_format_insight_results_no_results(self):
        """Test formatting when no results are found."""
        result = self.node._format_insight_results([], "test query")

        self.assertIn("No insights found matching 'test query'", result)
        self.assertIn("Suggest that the user try", result)

    def test_format_insight_results_single_result(self):
        """Test formatting for single insight result."""
        results = [
            {
                "id": self.insight1.id,
                "short_id": "abc123",
                "name": "Daily Pageviews",
                "description": "Track daily website traffic",
                "query": {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery"}},
                "filters": {},
            }
        ]

        result = self.node._format_insight_results(results, "pageviews")

        self.assertIn("Found 1 insight matching 'pageviews'", result)
        self.assertIn("**1. Daily Pageviews**", result)
        self.assertIn("Track daily website traffic", result)
        self.assertIn("/insights/abc123", result)
        self.assertIn("TrendsQuery analysis", result)
        self.assertIn("INSTRUCTIONS: Ask the user if they want to modify this insight", result)

    def test_format_insight_results_multiple_results(self):
        """Test formatting for multiple insight results."""
        results = [
            {
                "id": self.insight1.id,
                "short_id": "abc123",
                "name": "Daily Pageviews",
                "description": "Track daily website traffic",
                "query": {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery"}},
                "filters": {},
            },
            {
                "id": self.insight2.id,
                "short_id": "def456",
                "name": "User Signup Funnel",
                "description": "Track user conversion",
                "query": {"kind": "InsightVizNode", "source": {"kind": "FunnelsQuery"}},
                "filters": {},
            },
        ]

        result = self.node._format_insight_results(results, "analysis")

        self.assertIn("Found 2 insights matching 'analysis'", result)
        self.assertIn("**1. Daily Pageviews**", result)
        self.assertIn("**2. User Signup Funnel**", result)
        self.assertIn("INSTRUCTIONS: Ask the user if they want to modify one of these insights", result)

    @patch("ee.hogai.graph.insights.nodes.ChatOpenAI")
    def test_run_with_semantic_filtering(self, mock_openai):
        """Test full run method with semantic filtering enabled."""

        # Create a valid conversation
        conversation = Conversation.objects.create(team=self.team, user=self.user)

        # Mock structured output for single-pass selection
        mock_structured_model = MagicMock()
        mock_structured_model.invoke.return_value = {
            "selected_insight": "Daily Pageviews",
            "confidence": 0.9,
            "reasoning": "Direct match for pageview insights",
        }
        mock_openai.return_value.with_structured_output.return_value = mock_structured_model

        state = AssistantState(
            messages=[HumanMessage(content="Find pageview insights")],
            search_insights_query="pageview insights",
            root_tool_call_id="test_tool_call_id_3",  # Set the tool call ID for the test
        )

        result = self.node.run(state, {"configurable": {"thread_id": str(conversation.id)}})

        self.assertIsInstance(result, PartialAssistantState)
        self.assertEqual(len(result.messages), 1)
        self.assertIsInstance(result.messages[0], AssistantToolCallMessage)
        self.assertEqual(result.messages[0].tool_call_id, "test_tool_call_id_3")
        self.assertIn("Found", result.messages[0].content)
        self.assertIn("INSTRUCTIONS:", result.messages[0].content)
        self.assertEqual(result.search_insights_query, "")  # Should reset state

    def test_run_with_no_query(self):
        """Test run method with no search query."""

        # Create a valid conversation
        conversation = Conversation.objects.create(team=self.team, user=self.user)

        state = AssistantState(
            messages=[HumanMessage(content="test")],
            search_insights_query=None,
            root_tool_call_id="test_tool_call_id_2",  # Set the tool call ID for the test
        )

        result = self.node.run(state, {"configurable": {"thread_id": str(conversation.id)}})

        self.assertIsInstance(result, PartialAssistantState)
        self.assertEqual(len(result.messages), 1)
        self.assertIsInstance(result.messages[0], AssistantToolCallMessage)
        self.assertEqual(result.messages[0].tool_call_id, "test_tool_call_id_2")
        self.assertIn("Found", result.messages[0].content)
        self.assertIn("INSTRUCTIONS:", result.messages[0].content)
        self.assertEqual(result.search_insights_query, "")

    def test_search_insights_team_filtering(self):
        """Test that search only returns insights from the correct team."""
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

        results, _cache_stats = self.node._search_insights()

        # Should only return insights from self.team
        for result in results:
            insight_id = result.get("insight_id") or result.get("id")
            if insight_id:
                insight = Insight.objects.filter(id=insight_id).first()
                self.assertEqual(insight.team, self.team)

    def test_semantic_filter_with_empty_results(self):
        """Test semantic filtering with empty input."""
        results = self.node._semantic_filter_insights([], "test query")
        self.assertEqual(results, [])
