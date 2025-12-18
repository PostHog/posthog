from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status


class TestLLMGatewayViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.id}/llm_gateway"

    @patch("posthog.api.llm_gateway.http.asyncio.run")
    @patch("posthog.api.llm_gateway.http.litellm.anthropic_messages")
    def test_anthropic_messages_non_streaming(self, _mock_anthropic, mock_asyncio_run):
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "id": "msg_01XYZ",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello! How can I help you?"}],
            "model": "claude-sonnet-4-20250514",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 25},
        }
        mock_asyncio_run.return_value = mock_response

        response = self.client.post(
            f"{self.base_url}/v1/messages/",
            data={
                "model": "claude-sonnet-4-20250514",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 1024,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["id"], "msg_01XYZ")
        self.assertEqual(data["type"], "message")
        self.assertEqual(data["role"], "assistant")

        mock_asyncio_run.assert_called_once()

    @patch("posthog.api.llm_gateway.http.asyncio.run")
    @patch("posthog.api.llm_gateway.http.litellm.anthropic_messages")
    def test_anthropic_messages_with_all_params(self, _mock_anthropic, mock_asyncio_run):
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "id": "msg_01XYZ",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Response"}],
            "model": "claude-sonnet-4-20250514",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        mock_asyncio_run.return_value = mock_response

        response = self.client.post(
            f"{self.base_url}/v1/messages/",
            data={
                "model": "claude-sonnet-4-20250514",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 2048,
                "temperature": 0.7,
                "top_p": 0.9,
                "top_k": 10,
                "system": "You are helpful",
                "tools": [{"name": "get_weather"}],
                "tool_choice": {"type": "auto"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_asyncio_run.assert_called_once()

    def test_anthropic_messages_missing_model(self):
        response = self.client.post(
            f"{self.base_url}/v1/messages/",
            data={
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 1024,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.json())

    def test_anthropic_messages_missing_messages(self):
        response = self.client.post(
            f"{self.base_url}/v1/messages/",
            data={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1024,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.json())

    @patch("posthog.api.llm_gateway.http.litellm.completion")
    def test_chat_completions_non_streaming(self, mock_completion):
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1677652288,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello! How can I help?"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }
        mock_completion.return_value = mock_response

        response = self.client.post(
            f"{self.base_url}/v1/chat/completions/",
            data={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["id"], "chatcmpl-123")
        self.assertEqual(data["object"], "chat.completion")
        mock_completion.assert_called_once()

    @patch("posthog.api.llm_gateway.http.litellm.completion")
    def test_chat_completions_with_all_params(self, mock_completion):
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1677652288,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Response"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        mock_completion.return_value = mock_response

        response = self.client.post(
            f"{self.base_url}/v1/chat/completions/",
            data={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
                "temperature": 0.7,
                "max_tokens": 1000,
                "tools": [{"type": "function", "function": {"name": "test"}}],
                "tool_choice": "auto",
                "reasoning_effort": "medium",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_completion.assert_called_once()

    def test_chat_completions_missing_model(self):
        response = self.client.post(
            f"{self.base_url}/v1/chat/completions/",
            data={
                "messages": [{"role": "user", "content": "Hello"}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.json())

    def test_chat_completions_missing_messages(self):
        response = self.client.post(
            f"{self.base_url}/v1/chat/completions/",
            data={
                "model": "gpt-4",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.json())

    def test_requires_authentication(self):
        self.client.logout()
        response = self.client.post(
            f"{self.base_url}/v1/messages/",
            data={
                "model": "claude-sonnet-4-20250514",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 1024,
            },
            format="json",
        )
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    @patch("posthog.api.llm_gateway.http.posthoganalytics.capture")
    @patch("posthog.api.llm_gateway.http.asyncio.run")
    @patch("posthog.api.llm_gateway.http.litellm.anthropic_messages")
    def test_anthropic_messages_captures_analytics_event(self, _mock_anthropic, mock_asyncio_run, mock_capture):
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "id": "msg_01XYZ",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello! How can I help you?"}],
            "model": "claude-sonnet-4-20250514",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 25},
        }
        mock_asyncio_run.return_value = mock_response

        response = self.client.post(
            f"{self.base_url}/v1/messages/",
            data={
                "model": "claude-sonnet-4-20250514",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 1024,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args[1]

        self.assertEqual(call_kwargs["event"], "$ai_generation")
        self.assertEqual(call_kwargs["distinct_id"], str(self.user.distinct_id))

        properties = call_kwargs["properties"]
        self.assertEqual(properties["$ai_model"], "claude-sonnet-4-20250514")
        self.assertEqual(properties["$ai_input"], [{"role": "user", "content": "Hello"}])
        self.assertEqual(properties["$ai_input_tokens"], 10)
        self.assertEqual(properties["$ai_output_tokens"], 25)
        self.assertEqual(properties["$ai_http_status"], 200)
        self.assertEqual(properties["team_id"], self.team.id)
        self.assertEqual(properties["organization_id"], str(self.organization.id))
        self.assertIn("$ai_latency", properties)
        self.assertIn("$ai_trace_id", properties)
        self.assertIn("$ai_span_id", properties)
        self.assertIn("$ai_output_choices", properties)
        self.assertEqual(len(properties["$ai_output_choices"]), 1)
        self.assertEqual(properties["$ai_output_choices"][0]["role"], "assistant")
        self.assertEqual(properties["$ai_output_choices"][0]["content"], "Hello! How can I help you?")

        groups = call_kwargs["groups"]
        self.assertEqual(groups["organization"], str(self.organization.id))
        self.assertEqual(groups["project"], str(self.team.id))

    @patch("posthog.api.llm_gateway.http.posthoganalytics.capture")
    @patch("posthog.api.llm_gateway.http.asyncio.run")
    @patch("posthog.api.llm_gateway.http.litellm.anthropic_messages")
    def test_anthropic_messages_captures_error_event(self, _mock_anthropic, mock_asyncio_run, mock_capture):
        mock_asyncio_run.side_effect = Exception("API Error")

        response = self.client.post(
            f"{self.base_url}/v1/messages/",
            data={
                "model": "claude-sonnet-4-20250514",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 1024,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args[1]

        self.assertEqual(call_kwargs["event"], "$ai_generation")

        properties = call_kwargs["properties"]
        self.assertEqual(properties["$ai_is_error"], True)
        self.assertEqual(properties["$ai_error"], "API Error")
        self.assertEqual(properties["$ai_http_status"], 500)

    @patch("posthog.api.llm_gateway.http.asyncio.run")
    @patch("posthog.api.llm_gateway.http.litellm.anthropic_messages")
    def test_anthropic_messages_with_client_name(self, mock_anthropic, mock_asyncio_run):
        """Test that client name from URL path is passed to metadata."""
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "id": "msg_01XYZ",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello!"}],
            "model": "claude-sonnet-4-20250514",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        mock_asyncio_run.return_value = mock_response

        response = self.client.post(
            f"{self.base_url}/wizard/v1/messages/",
            data={
                "model": "claude-sonnet-4-20250514",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 1024,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check that anthropic_messages was called with correct metadata
        mock_anthropic.assert_called_once()
        call_kwargs = mock_anthropic.call_args[1]
        self.assertEqual(call_kwargs["metadata"]["ai_product"], "wizard")

    @patch("posthog.api.llm_gateway.http.asyncio.run")
    @patch("posthog.api.llm_gateway.http.litellm.anthropic_messages")
    def test_anthropic_messages_default_ai_product(self, mock_anthropic, mock_asyncio_run):
        """Test that default ai_product is 'llm_gateway' when no client name provided."""
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "id": "msg_01XYZ",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello!"}],
            "model": "claude-sonnet-4-20250514",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        mock_asyncio_run.return_value = mock_response

        response = self.client.post(
            f"{self.base_url}/v1/messages/",
            data={
                "model": "claude-sonnet-4-20250514",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 1024,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_anthropic.assert_called_once()
        call_kwargs = mock_anthropic.call_args[1]
        self.assertEqual(call_kwargs["metadata"]["ai_product"], "llm_gateway")

    @patch("posthog.api.llm_gateway.http.litellm.completion")
    def test_chat_completions_with_client_name(self, mock_completion):
        """Test that client name from URL path is passed to metadata for chat completions."""
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1677652288,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        mock_completion.return_value = mock_response

        response = self.client.post(
            f"{self.base_url}/wizard/v1/chat/completions/",
            data={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_completion.assert_called_once()
        call_kwargs = mock_completion.call_args[1]
        self.assertEqual(call_kwargs["metadata"]["ai_product"], "wizard")

    @parameterized.expand(["invalid", "unknown", "foo", "maxai"])
    def test_anthropic_messages_invalid_product_returns_400(self, invalid_product):
        response = self.client.post(
            f"{self.base_url}/{invalid_product}/v1/messages/",
            data={
                "model": "claude-sonnet-4-20250514",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 1024,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        error = response.json()["error"]
        self.assertEqual(error["type"], "invalid_request_error")
        self.assertIn(invalid_product, error["message"])
        self.assertIn("llm_gateway", error["message"])
        self.assertIn("array", error["message"])
        self.assertIn("wizard", error["message"])

    @parameterized.expand(["invalid", "unknown", "foo", "maxai"])
    def test_chat_completions_invalid_product_returns_400(self, invalid_product):
        response = self.client.post(
            f"{self.base_url}/{invalid_product}/v1/chat/completions/",
            data={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        error = response.json()["error"]
        self.assertEqual(error["type"], "invalid_request_error")
        self.assertIn(invalid_product, error["message"])
        self.assertIn("llm_gateway", error["message"])
        self.assertIn("array", error["message"])
        self.assertIn("wizard", error["message"])
