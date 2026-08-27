from posthog.test.base import APIBaseTest
from unittest import mock

import openai
from parameterized import parameterized

from products.data_warehouse.backend.max_tools import HogQLQueryFixerTool
from products.data_warehouse.backend.presentation.views.fix_hogql import (
    FIXER_FAILED_MESSAGE,
    FIXER_NOT_CONFIGURED_MESSAGE,
)


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

    @parameterized.expand(
        [
            ("missing_credentials", openai.OpenAIError("The api_key client option must be set"), True, False),
            ("provider_failure", RuntimeError("upstream timeout"), False, True),
        ]
    )
    def test_create_returns_readable_error_when_fixer_raises(self, _name, raised, not_configured, reports):
        with (
            mock.patch.object(HogQLQueryFixerTool, "invoke", side_effect=raised),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.fix_hogql.capture_exception"
            ) as mock_capture,
        ):
            response = self.client.post(
                f"/api/environments/{self.team.id}/fix_hogql/",
                {"query": "select timestam from events", "error": "Unable to resolve field: timestam"},
            )

        assert response.status_code == 400
        data = response.json()
        assert data["error"] == (FIXER_NOT_CONFIGURED_MESSAGE if not_configured else FIXER_FAILED_MESSAGE)
        assert data["trace_id"].startswith("fix_hogql_query_")
        assert mock_capture.called is reports

    @parameterized.expand(
        [
            ("without_connection", None, {"hogql_query": "q", "error_message": "e"}),
            (
                "with_connection",
                "018f0000-0000-0000-0000-000000000000",
                {
                    "hogql_query": "q",
                    "error_message": "e",
                    "connection_id": "018f0000-0000-0000-0000-000000000000",
                },
            ),
        ]
    )
    def test_context_passed_correctly(self, _name, connection_id, expected_context):
        query = "select timestam from events"
        error = "Unable to resolve field: timestam"
        expected_context = {**expected_context, "hogql_query": query, "error_message": error}

        captured_tool = None

        def capture_tool_init(original_init):
            def wrapper(self, *args, **kwargs):
                nonlocal captured_tool
                result = original_init(self, *args, **kwargs)
                captured_tool = self
                return result

            return wrapper

        body = {"query": query, "error": error}
        if connection_id is not None:
            body["connection_id"] = connection_id

        with (
            mock.patch("products.data_warehouse.backend.max_tools.MaxChatOpenAI"),
            mock.patch.object(HogQLQueryFixerTool, "_parse_output", return_value="select timestamp from events"),
            mock.patch.object(HogQLQueryFixerTool, "__init__", capture_tool_init(HogQLQueryFixerTool.__init__)),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.id}/fix_hogql/",
                body,
            )

            assert response.status_code == 200
            assert captured_tool is not None
            assert captured_tool.context == expected_context
