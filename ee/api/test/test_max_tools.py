from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event
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

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "application/json")

        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["type"], "message")

        mock_generate.assert_called_once()

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


class TestInvokeToolAPI(ClickhouseTestMixin, APIBaseTest):
    def test_invoke_tool_not_found(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/invoke/nonexistent_tool/",
            {"args": {}},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"], "tool_not_found")

    def test_invoke_execute_sql_with_invalid_args(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/invoke/execute_sql/",
            {"args": {"query": ""}},  # missing viz_title and viz_description
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"], "validation_error")

    def test_invoke_execute_sql_with_invalid_query(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/invoke/execute_sql/",
            {
                "args": {
                    "query": "INVALID SQL SYNTAX",
                    "viz_title": "Test",
                    "viz_description": "Test description",
                }
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"], "validation_error")

    def test_invoke_execute_sql_success(self):
        _create_event(team=self.team, distinct_id="user1", event="test_event")

        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/invoke/execute_sql/",
            {
                "args": {
                    "query": "SELECT event, count() as cnt FROM events GROUP BY event",
                    "viz_title": "Event counts",
                    "viz_description": "Count events by type",
                }
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIn("test_event", data["content"])
        self.assertIsNotNone(data["data"])
