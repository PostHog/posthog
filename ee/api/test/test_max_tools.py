from posthog.test.base import APIBaseTest
from unittest.mock import patch

from mistralai_azure import AssistantMessage

from ee.hogai.insights_assistant import InsightsAssistant


class TestMaxToolsAPI(APIBaseTest):
    @patch.object(InsightsAssistant, "invoke")
    def test_create_and_query_insight_returns_json(self, mock_generate):
        mock_generate.return_value = [("message", AssistantMessage(content="Creating your insight", role="assistant"))]

        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/create_and_query_insight/",
            {"query": "Show me daily active users", "insight_type": "trends"},
            format="json",
        )

        assert response.status_code == 200
        assert response.headers["Content-Type"] == "application/json"

        data = response.json()
        assert len(data) == 1
        assert data[0]["type"] == "message"

        mock_generate.assert_called_once()

    def test_create_and_query_insight_missing_insight_type(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/create_and_query_insight/",
            {"query": "Show me data"},
            format="json",
        )

        assert response.status_code == 400
        error = response.json()
        assert error["attr"] == "insight_type"
        assert error["code"] == "required"

    def test_create_and_query_insight_invalid_insight_type(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/create_and_query_insight/",
            {"query": "Show me data", "insight_type": "invalid_type"},
            format="json",
        )

        assert response.status_code == 400
        error = response.json()
        assert error["attr"] == "insight_type"
