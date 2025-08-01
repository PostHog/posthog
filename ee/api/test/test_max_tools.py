from unittest.mock import patch

from mistralai_azure import AssistantMessage

from ee.hogai.assistant_factory import AssistantFactory
from posthog.test.base import APIBaseTest


class TestMaxToolsAPI(APIBaseTest):
    @patch.object(AssistantFactory, "create")
    def test_create_and_query_insight_returns_json(self, mock_factory_create):
        # Create a mock assistant with the invoke method
        mock_assistant = mock_factory_create.return_value
        mock_assistant.invoke.return_value = [
            ("message", AssistantMessage(content="Creating your insight", role="assistant"))
        ]

        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/create_and_query_insight/",
            {"query": "Show me daily active users", "insight_type": "trends"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "application/json")

        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["type"], "message")

        mock_factory_create.assert_called_once()
        mock_assistant.invoke.assert_called_once()

    def test_create_and_query_insight_missing_insight_type(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/create_and_query_insight/",
            {"query": "Show me data"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        error = response.json()
        self.assertEqual(error["attr"], "insight_type")
        self.assertEqual(error["code"], "required")

    def test_create_and_query_insight_invalid_insight_type(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/create_and_query_insight/",
            {"query": "Show me data", "insight_type": "invalid_type"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        error = response.json()
        self.assertEqual(error["attr"], "insight_type")
