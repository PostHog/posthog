from unittest.mock import patch, MagicMock
from django.utils import timezone


from ee.hogai.graph.insights.nodes import InsightSearchNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.models.assistant import Conversation
from posthog.models import Insight, InsightViewed
from posthog.schema import AssistantMessage, HumanMessage
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

    def test_router_returns_end(self):
        """Test that router returns 'end' as expected."""
        result = self.node.router(AssistantState(messages=[]))
        self.assertEqual(result, "end")

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
        filters_data = {}

        result = self.node._summarize_query_data(query_data, filters_data)
        self.assertEqual(result, "TrendsQuery analysis (InsightVizNode)")

    def test_summarize_query_data_with_legacy_format(self):
        """Test query data summarization for legacy filters format."""
        query_data = {}
        filters_data = {"insight": "FUNNELS"}

        result = self.node._summarize_query_data(query_data, filters_data)
        self.assertEqual(result, "FUNNELS analysis (legacy format)")

    def test_summarize_query_data_with_no_data(self):
        """Test query data summarization with no data."""
        result = self.node._summarize_query_data({}, {})
        self.assertEqual(result, "No query data available")

    @patch("ee.hogai.graph.insights.nodes.ChatOpenAI")
    def test_semantic_filter_insights(self, mock_openai):
        """Test semantic filtering with mocked LLM."""
        # Mock structured output response
        mock_structured_model = MagicMock()
        mock_structured_model.invoke.return_value = {"high": ["Daily Pageviews"], "medium": [], "low": [], "none": []}
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
        self.assertEqual(results[0]["relevance_score"], 1.0)  # high rating
        mock_structured_model.invoke.assert_called_once()

    @patch("ee.hogai.graph.insights.nodes.ChatOpenAI")
    def test_semantic_filter_insights_low_relevance(self, mock_openai):
        """Test semantic filtering filters out low relevance insights."""
        # Mock LLM response with low relevance in batch format
        mock_response = MagicMock()
        mock_response.content = "1: low"
        mock_openai.return_value.invoke.return_value = mock_response

        insights = [
            {
                "insight_id": self.insight1.id,
                "insight__name": "Daily Pageviews",
                "insight__description": "Track daily website traffic",
                "insight__derived_name": None,
            }
        ]

        results = self.node._semantic_filter_insights(insights, "user signup")

        self.assertEqual(len(results), 0)  # Should filter out low relevance

    @patch("ee.hogai.graph.insights.nodes.ChatOpenAI")
    def test_select_best_insight_single_insight(self, mock_openai):
        """Test selecting best insight when only one insight exists."""
        insights = [{"id": self.insight1.id, "name": "Daily Pageviews"}]

        result = self.node._select_best_insight(insights, "pageviews")

        self.assertEqual(result, insights[0])
        # Should not call LLM for single insight
        mock_openai.return_value.invoke.assert_not_called()

    @patch("ee.hogai.graph.insights.nodes.ChatOpenAI")
    def test_select_best_insight_multiple_insights(self, mock_openai):
        """Test selecting best insight from multiple options."""
        # Mock LLM response selecting second insight
        mock_response = MagicMock()
        mock_response.content = "2"
        mock_openai.return_value.invoke.return_value = mock_response

        insights = [
            {"id": self.insight1.id, "name": "Daily Pageviews", "relevance_score": 0.8},
            {"id": self.insight2.id, "name": "User Signup Funnel", "relevance_score": 0.9},
        ]

        result = self.node._select_best_insight(insights, "signup funnel")

        self.assertEqual(result["id"], self.insight2.id)
        mock_openai.return_value.invoke.assert_called_once()

    @patch("ee.hogai.graph.insights.nodes.ChatOpenAI")
    def test_select_best_insight_fallback_on_error(self, mock_openai):
        """Test fallback to highest relevance score when LLM fails."""
        # Mock LLM to return invalid response
        mock_response = MagicMock()
        mock_response.content = "invalid_number"
        mock_openai.return_value.invoke.return_value = mock_response

        insights = [
            {"id": self.insight1.id, "name": "Daily Pageviews", "relevance_score": 0.8},
            {"id": self.insight2.id, "name": "User Signup Funnel", "relevance_score": 0.9},
        ]

        result = self.node._select_best_insight(insights, "test query")

        # Should fallback to highest relevance score
        self.assertEqual(result["id"], self.insight2.id)

    def test_format_insight_results_no_results(self):
        """Test formatting when no results are found."""
        result = self.node._format_insight_results([], "test query")

        self.assertIn("No insights found matching 'test query'", result)
        self.assertIn("Using different keywords", result)

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
        self.assertIn("modify this insight", result)

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
        self.assertIn("explore any of these insights further", result)

    @patch("ee.hogai.graph.insights.nodes.ChatOpenAI")
    def test_run_with_semantic_filtering(self, mock_openai):
        """Test full run method with semantic filtering enabled."""

        # Create a valid conversation
        conversation = Conversation.objects.create(team=self.team, user=self.user)

        # Mock semantic filtering LLM
        semantic_mock = MagicMock()
        semantic_mock.content = "high"

        # Mock best insight selection LLM
        selection_mock = MagicMock()
        selection_mock.content = "1"

        mock_openai.return_value.invoke.side_effect = [semantic_mock, selection_mock]

        state = AssistantState(
            messages=[HumanMessage(content="Find pageview insights")], root_to_search_insights="pageview insights"
        )

        result = self.node.run(state, {"configurable": {"thread_id": str(conversation.id)}})

        self.assertIsInstance(result, PartialAssistantState)
        self.assertEqual(len(result.messages), 1)
        self.assertIsInstance(result.messages[0], AssistantMessage)
        self.assertIn("Found", result.messages[0].content)
        self.assertEqual(result.root_to_search_insights, "")  # Should reset state

    def test_run_without_semantic_filtering(self):
        """Test run method without semantic filtering (short query)."""

        # Create a valid conversation
        conversation = Conversation.objects.create(team=self.team, user=self.user)

        state = AssistantState(
            messages=[HumanMessage(content="abc")],
            root_to_search_insights="ab",  # Too short for semantic filtering
        )

        result = self.node.run(state, {"configurable": {"thread_id": str(conversation.id)}})

        self.assertIsInstance(result, PartialAssistantState)
        self.assertEqual(len(result.messages), 1)
        self.assertIsInstance(result.messages[0], AssistantMessage)
        self.assertEqual(result.root_to_search_insights, "")

    def test_run_with_no_query(self):
        """Test run method with no search query."""

        # Create a valid conversation
        conversation = Conversation.objects.create(team=self.team, user=self.user)

        state = AssistantState(messages=[HumanMessage(content="test")], root_to_search_insights=None)

        result = self.node.run(state, {"configurable": {"thread_id": str(conversation.id)}})

        self.assertIsInstance(result, PartialAssistantState)
        self.assertEqual(len(result.messages), 1)
        self.assertEqual(result.root_to_search_insights, "")

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

    def test_select_best_insight_with_no_query(self):
        """Test selecting best insight when no query provided."""
        insights = [
            {"id": 1, "relevance_score": 0.7},
            {"id": 2, "relevance_score": 0.9},
        ]

        result = self.node._select_best_insight(insights, None)

        # Should return highest relevance score
        self.assertEqual(result["id"], 2)

    def test_select_best_insight_with_empty_list(self):
        """Test selecting best insight with empty list."""
        result = self.node._select_best_insight([], "test query")
        self.assertIsNone(result)
