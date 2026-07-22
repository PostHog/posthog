from posthog.test.base import APIBaseTest
from unittest import mock

from langchain_core.exceptions import OutputParserException

from products.data_warehouse.backend.max_tools import HogQLQueryFixerTool


class TestFixHogQL(APIBaseTest):
    def test_create(self):
        with (
            mock.patch("products.data_warehouse.backend.max_tools.MaxChatOpenAI"),
            mock.patch.object(HogQLQueryFixerTool, "_parse_output", return_value="select timestamp from events"),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.id}/fix_hogql/",
                {"query": "select timestam from events", "error": "Unable to resolve field: timestam"},
            )

            assert response.status_code == 200

    def test_truncated_llm_output_degrades_to_400(self):
        # langchain raises OutputParserException when the model's function-call arguments are
        # truncated/malformed JSON. It must be retried and fall through to the graceful
        # "Could not fix the query" 400, not surface as an unhandled 500.
        failing_model = mock.MagicMock()
        failing_model.invoke.side_effect = OutputParserException(
            'Function output arguments:\n\n{"query": "WITH dates AS (\n\nare not valid JSON.'
        )

        with mock.patch.object(
            HogQLQueryFixerTool, "_model", new_callable=mock.PropertyMock, return_value=failing_model
        ):
            response = self.client.post(
                f"/api/environments/{self.team.id}/fix_hogql/",
                {"query": "WITH dates AS (select 1)", "error": "some error"},
            )

        assert response.status_code == 400
        assert response.json()["error"] == "Could not fix the query"
        # Retried the full loop rather than bailing on the first parse failure.
        assert failing_model.invoke.call_count == 3

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
            mock.patch("products.data_warehouse.backend.max_tools.MaxChatOpenAI"),
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
