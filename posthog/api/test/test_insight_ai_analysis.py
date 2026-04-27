from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from rest_framework import status

from posthog.schema import EventsNode, InsightVizNode, TrendsQuery

from posthog.models import Insight


class TestInsightAnalyze(ClickhouseTestMixin, APIBaseTest):
    """Covers the AI analysis endpoint's handling of edge cases.

    See ``posthog.api.insight.InsightsViewSet.analyze`` and the corresponding
    ``InsightAIAnalysis`` UI in the frontend — when no cached results exist we
    must surface a structured reason instead of silently returning ``""``.
    """

    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

    def _create_insight_with_query(self) -> Insight:
        return Insight.objects.create(
            team=self.team,
            name="Test insight",
            query=InsightVizNode(source=TrendsQuery(series=[EventsNode(event="$pageview")])).model_dump(),
        )

    def test_analyze_returns_structured_reason_when_no_query(self) -> None:
        insight = Insight.objects.create(team=self.team, name="No query")

        response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight.id}/analyze/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"result": "", "reason": "no_query"})

    def test_analyze_returns_structured_reason_when_no_cached_results(self) -> None:
        insight = self._create_insight_with_query()

        with (
            patch("posthog.api.insight.process_query_model", return_value={"results": None, "result": None}),
            patch("posthog.api.insight.get_insight_analysis") as mock_analysis,
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight.id}/analyze/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"result": "", "reason": "no_cached_results"})
        # Critically, we must not have wasted an LLM call on empty data.
        mock_analysis.assert_not_called()

    def test_analyze_returns_structured_reason_when_cache_lookup_raises(self) -> None:
        insight = self._create_insight_with_query()

        with (
            patch("posthog.api.insight.process_query_model", side_effect=RuntimeError("cache miss")),
            patch("posthog.api.insight.get_insight_analysis") as mock_analysis,
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight.id}/analyze/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"result": "", "reason": "no_cached_results"})
        mock_analysis.assert_not_called()

    def test_analyze_runs_when_results_present(self) -> None:
        insight = self._create_insight_with_query()

        with (
            patch(
                "posthog.api.insight.process_query_model",
                return_value={"results": [{"data": [1, 2, 3], "label": "$pageview"}]},
            ),
            patch("posthog.api.insight.get_insight_analysis", return_value="An analysis") as mock_analysis,
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight.id}/analyze/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"result": "An analysis"})
        mock_analysis.assert_called_once()

    def test_analyze_surfaces_llm_failure_as_api_exception(self) -> None:
        insight = self._create_insight_with_query()

        with (
            patch(
                "posthog.api.insight.process_query_model",
                return_value={"results": [{"data": [1, 2, 3], "label": "$pageview"}]},
            ),
            patch(
                "posthog.api.insight.get_insight_analysis",
                side_effect=RuntimeError("internal LLM detail"),
            ),
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight.id}/analyze/")

        # The frontend's analysisError reducer needs a populated `detail` to show a
        # real error instead of an empty body, but we must not echo the underlying
        # exception text back (CodeQL: information exposure through an exception).
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        body = response.json()
        self.assertIn("Failed to generate analysis", body["detail"])
        self.assertNotIn("internal LLM detail", body["detail"])

    def test_analyze_blocked_without_ai_consent(self) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        insight = self._create_insight_with_query()

        response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight.id}/analyze/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
