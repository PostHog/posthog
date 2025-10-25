from posthog.test.base import APIBaseTest
from unittest import mock

from products.data_warehouse.backend.hogql_fixer_ai import HogQLQueryFixerTool


class TestFixHogQL(APIBaseTest):
    def test_create(self):
        with (
            mock.patch("products.data_warehouse.backend.hogql_fixer_ai.ChatOpenAI"),
            mock.patch.object(HogQLQueryFixerTool, "_parse_output", return_value="select timestamp from events"),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.id}/fix_hogql/",
                {"query": "select timestam from events", "error": "Unable to resolve field: timestam"},
            )

            assert response.status_code == 200

    def test_context_passed_correctly(self):
        query = "select timestam from events"
        error = "Unable to resolve field: timestam"

        captured_tool = None

        def capture_tool_init(original_init):
            def wrapper(self, *args, **kwargs):
                nonlocal captured_tool
                result = original_init(self, *args, **kwargs)
                captured_tool = self
                return result

            return wrapper

        with (
            mock.patch("products.data_warehouse.backend.hogql_fixer_ai.ChatOpenAI"),
            mock.patch.object(HogQLQueryFixerTool, "_parse_output", return_value="select timestamp from events"),
            mock.patch.object(HogQLQueryFixerTool, "__init__", capture_tool_init(HogQLQueryFixerTool.__init__)),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.id}/fix_hogql/",
                {"query": query, "error": error},
            )

            assert response.status_code == 200
            assert captured_tool is not None
            assert captured_tool.context == {
                "hogql_query": query,
                "error_message": error,
            }
