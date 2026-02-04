from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

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


class TestInvokeToolAPI(APIBaseTest):
    def test_invoke_tool_not_found(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/invoke/nonexistent_tool/",
            {"args": {}},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertTrue(data["isError"])
        self.assertIn("not found", data["content"])

    def test_invoke_execute_sql_with_invalid_args(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/invoke/execute_sql/",
            {"args": {}},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertTrue(data["isError"])
        self.assertIn("validation error", data["content"].lower())

    @patch("ee.hogai.tools.execute_sql.external.ExecuteSQLExternalTool.execute", new_callable=AsyncMock)
    def test_invoke_execute_sql_success(self, mock_execute):
        mock_execute.return_value = ("event | cnt\ntest_event | 5", {"query": "SELECT event"})

        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/invoke/execute_sql/",
            {"args": {"query": "SELECT event, count() as cnt FROM events GROUP BY event"}},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotIn("isError", data)
        self.assertIn("test_event", data["content"])
        self.assertIsNotNone(data["data"])
        mock_execute.assert_called_once()

    @patch("ee.hogai.tools.execute_sql.external.ExecuteSQLExternalTool.execute", new_callable=AsyncMock)
    def test_invoke_tool_error_returns_error_response(self, mock_execute):
        from ee.hogai.tool_errors import MaxToolRetryableError

        mock_execute.side_effect = MaxToolRetryableError("Query validation failed: syntax error")

        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/invoke/execute_sql/",
            {"args": {"query": "BAD QUERY"}},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["isError"])
        self.assertIn("Tool failed", data["content"])

    @patch("ee.hogai.tools.execute_sql.external.ExecuteSQLExternalTool.execute", new_callable=AsyncMock)
    def test_invoke_tool_unexpected_error_returns_internal_error(self, mock_execute):
        mock_execute.side_effect = RuntimeError("unexpected")

        response = self.client.post(
            f"/api/environments/{self.team.id}/max_tools/invoke/execute_sql/",
            {"args": {"query": "SELECT 1"}},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["isError"])
        self.assertIn("internal error", data["content"].lower())
