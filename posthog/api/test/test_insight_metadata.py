from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

MOCK_PATH = "posthog.api.insight_suggestions.hit_openai"


def _make_query(source: dict) -> dict:
    return {"kind": "InsightVizNode", "source": source}


def _trends_query(**kwargs) -> dict:
    return _make_query({"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}], **kwargs})


class TestGenerateInsightMetadata(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.url = f"/api/projects/{self.team.id}/insights/generate_metadata/"

    @patch(MOCK_PATH)
    def test_returns_name_and_description(self, mock_openai):
        mock_openai.return_value = ('{"name": "Daily Pageviews", "description": "Tracks daily page views."}', 10, 20)
        response = self.client.post(self.url, {"query": _trends_query()}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "Daily Pageviews"
        assert response.json()["description"] == "Tracks daily page views."

    def test_missing_query_returns_400(self):
        response = self.client.post(self.url, {}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Missing" in response.json()["error"]

    @patch(MOCK_PATH, side_effect=Exception("LLM API error"))
    def test_llm_failure_returns_500(self, mock_openai):
        response = self.client.post(self.url, {"query": _trends_query()}, format="json")

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Failed" in response.json()["error"]

    def test_ai_not_approved_returns_403(self):
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        response = self.client.post(self.url, {"query": _trends_query()}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @parameterized.expand(
        [
            (
                "trends_with_breakdown",
                _make_query(
                    {
                        "kind": "TrendsQuery",
                        "series": [{"kind": "EventsNode", "event": "$pageview"}],
                        "breakdownFilter": {"breakdown": "$browser"},
                    }
                ),
            ),
            (
                "funnel",
                _make_query(
                    {
                        "kind": "FunnelsQuery",
                        "series": [
                            {"kind": "EventsNode", "event": "signup"},
                            {"kind": "EventsNode", "event": "purchase"},
                        ],
                    }
                ),
            ),
            (
                "paths",
                _make_query(
                    {
                        "kind": "PathsQuery",
                        "pathsFilter": {"includeEventTypes": ["$pageview"]},
                    }
                ),
            ),
        ]
    )
    @patch(MOCK_PATH)
    def test_accepts_various_query_types(self, _name, query, mock_openai):
        mock_openai.return_value = ('{"name": "Test Name", "description": "Test description."}', 10, 20)
        response = self.client.post(self.url, {"query": query}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "Test Name"
        assert response.json()["description"] == "Test description."
