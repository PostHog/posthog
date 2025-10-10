from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from rest_framework import status


class TestLLMGatewayViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.id}/llm_gateway"

    @patch("posthog.api.llm_gateway.http.asyncio.run")
    @patch("posthog.api.llm_gateway.http.litellm.anthropic_messages")
    def test_anthropic_messages_non_streaming(self, mock_anthropic, mock_asyncio_run):
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "id": "msg_01XYZ",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello! How can I help you?"}],
            "model": "claude-3-5-sonnet-20241022",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 25},
        }
        mock_asyncio_run.return_value = mock_response

        response = self.client.post(
            f"{self.base_url}/v1/messages/",
            data={
                "model": "claude-3-5-sonnet-20241022",
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
    def test_anthropic_messages_with_all_params(self, mock_anthropic, mock_asyncio_run):
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "id": "msg_01XYZ",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Response"}],
            "model": "claude-3-5-sonnet-20241022",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        mock_asyncio_run.return_value = mock_response

        response = self.client.post(
            f"{self.base_url}/v1/messages/",
            data={
                "model": "claude-3-5-sonnet-20241022",
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
                "model": "claude-3-5-sonnet-20241022",
                "max_tokens": 1024,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.json())

    @patch("posthog.api.llm_gateway.http.asyncio.run")
    @patch("posthog.api.llm_gateway.http.litellm.acompletion")
    def test_chat_completions_non_streaming(self, mock_completion, mock_asyncio_run):
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
        mock_completion.return_value = AsyncMock(return_value=mock_response)
        mock_asyncio_run.return_value = mock_response

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
        mock_asyncio_run.assert_called_once()

    @patch("posthog.api.llm_gateway.http.asyncio.run")
    @patch("posthog.api.llm_gateway.http.litellm.acompletion")
    def test_chat_completions_with_all_params(self, mock_completion, mock_asyncio_run):
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
        mock_completion.return_value = AsyncMock(return_value=mock_response)
        mock_asyncio_run.return_value = mock_response

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
        mock_asyncio_run.assert_called_once()

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
                "model": "claude-3-5-sonnet-20241022",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 1024,
            },
            format="json",
        )
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])
