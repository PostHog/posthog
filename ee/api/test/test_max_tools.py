from posthog.test.base import APIBaseTest
from unittest.mock import patch

from mistralai_azure import AssistantMessage
from parameterized import parameterized

from posthog.event_usage import EventSource

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

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "application/json")

        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["type"], "message")

        mock_generate.assert_called_once()

    @parameterized.expand(
        [
            ("mcp_client_header", {"HTTP_X_POSTHOG_CLIENT": "mcp"}, EventSource.MCP),
            (
                "cli_wrapping_mcp",
                {"HTTP_X_POSTHOG_CLIENT": "mcp", "HTTP_X_POSTHOG_MCP_CONSUMER": "posthog-cli"},
                EventSource.CLI,
            ),
        ]
    )
    @patch("ee.hogai.insights_assistant.InsightsAssistant")
    def test_create_and_query_insight_attributes_to_the_calling_surface(
        self, _name, headers, expected_source, mock_assistant
    ):
        mock_assistant.return_value.invoke.return_value = []

        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/create_and_query_insight/",
            {"query": "Show me daily active users", "insight_type": "trends"},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_assistant.call_args.kwargs["event_source"], expected_source)

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
