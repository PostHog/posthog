from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import PersonalAPIKey
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal


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
            "model": "claude-3-5-haiku-20241022",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 25},
        }
        mock_asyncio_run.return_value = mock_response

        response = self.client.post(
            f"{self.base_url}/v1/messages/",
            data={
                "model": "claude-3-5-haiku-20241022",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 1024,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == "msg_01XYZ"
        assert data["type"] == "message"
        assert data["role"] == "assistant"

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
            "model": "claude-3-5-haiku-20241022",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        mock_asyncio_run.return_value = mock_response

        response = self.client.post(
            f"{self.base_url}/v1/messages/",
            data={
                "model": "claude-3-5-haiku-20241022",
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

        assert response.status_code == status.HTTP_200_OK
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

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in response.json()

    def test_anthropic_messages_missing_messages(self):
        response = self.client.post(
            f"{self.base_url}/v1/messages/",
            data={
                "model": "claude-3-5-haiku-20241022",
                "max_tokens": 1024,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in response.json()

    @patch("posthog.api.llm_gateway.http.litellm.completion")
    def test_chat_completions_non_streaming(self, mock_completion):
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1677652288,
            "model": "gpt-4o-mini",
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
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == "chatcmpl-123"
        assert data["object"] == "chat.completion"
        mock_completion.assert_called_once()

    @patch("posthog.api.llm_gateway.http.litellm.completion")
    def test_chat_completions_with_all_params(self, mock_completion):
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1677652288,
            "model": "gpt-4o-mini",
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
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Hello"}],
                "temperature": 0.7,
                "max_tokens": 1000,
                "tools": [{"type": "function", "function": {"name": "test"}}],
                "tool_choice": "auto",
                "reasoning_effort": "medium",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        mock_completion.assert_called_once()

    def test_chat_completions_missing_model(self):
        response = self.client.post(
            f"{self.base_url}/v1/chat/completions/",
            data={
                "messages": [{"role": "user", "content": "Hello"}],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in response.json()

    def test_chat_completions_missing_messages(self):
        response = self.client.post(
            f"{self.base_url}/v1/chat/completions/",
            data={
                "model": "gpt-4o-mini",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in response.json()

    def test_requires_authentication(self):
        self.client.logout()
        response = self.client.post(
            f"{self.base_url}/v1/messages/",
            data={
                "model": "claude-3-5-haiku-20241022",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 1024,
            },
            format="json",
        )
        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]

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
            "model": "claude-3-5-haiku-20241022",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 25},
        }
        mock_asyncio_run.return_value = mock_response

        response = self.client.post(
            f"{self.base_url}/v1/messages/",
            data={
                "model": "claude-3-5-haiku-20241022",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 1024,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args[1]

        assert call_kwargs["event"] == "$ai_generation"
        assert call_kwargs["distinct_id"] == str(self.user.distinct_id)

        properties = call_kwargs["properties"]
        assert properties["$ai_model"] == "claude-3-5-haiku-20241022"
        assert properties["$ai_input"] == [{"role": "user", "content": "Hello"}]
        assert properties["$ai_input_tokens"] == 10
        assert properties["$ai_output_tokens"] == 25
        assert properties["$ai_http_status"] == 200
        assert properties["team_id"] == self.team.id
        assert properties["organization_id"] == str(self.organization.id)
        assert "$ai_latency" in properties
        assert "$ai_trace_id" in properties
        assert "$ai_span_id" in properties
        assert "$ai_output_choices" in properties
        assert len(properties["$ai_output_choices"]) == 1
        assert properties["$ai_output_choices"][0]["role"] == "assistant"
        assert properties["$ai_output_choices"][0]["content"] == "Hello! How can I help you?"

        groups = call_kwargs["groups"]
        assert groups["organization"] == str(self.organization.id)
        assert groups["project"] == str(self.team.id)

    @patch("posthog.api.llm_gateway.http.posthoganalytics.capture")
    @patch("posthog.api.llm_gateway.http.asyncio.run")
    @patch("posthog.api.llm_gateway.http.litellm.anthropic_messages")
    def test_anthropic_messages_captures_error_event(self, _mock_anthropic, mock_asyncio_run, mock_capture):
        mock_asyncio_run.side_effect = Exception("API Error")

        response = self.client.post(
            f"{self.base_url}/v1/messages/",
            data={
                "model": "claude-3-5-haiku-20241022",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 1024,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args[1]

        assert call_kwargs["event"] == "$ai_generation"

        properties = call_kwargs["properties"]
        assert properties["$ai_is_error"]
        assert properties["$ai_error"] == "API Error"
        assert properties["$ai_http_status"] == 500


class TestLLMGatewayRateLimits(APIBaseTest):
    @parameterized.expand(
        [
            ("claude-3-5-haiku-20241022", "1000/minute", "20000/hour"),
            ("claude-3-haiku-20240307", "1000/minute", "20000/hour"),
            ("gpt-4o-mini", "100/minute", "1000/hour"),
            ("claude-3-5-sonnet-20241022", "100/minute", "1000/hour"),
            ("gpt-4o", "100/minute", "1000/hour"),
            (None, "100/minute", "1000/hour"),
        ]
    )
    def test_rate_limits_based_on_model(self, model, expected_burst, expected_sustained):
        from posthog.rate_limit import (
            LLM_GATEWAY_DEFAULT_BURST_RATE,
            LLM_GATEWAY_DEFAULT_SUSTAINED_RATE,
            _get_rate_for_model,
        )

        burst_rate = _get_rate_for_model(model, "burst", LLM_GATEWAY_DEFAULT_BURST_RATE)
        sustained_rate = _get_rate_for_model(model, "sustained", LLM_GATEWAY_DEFAULT_SUSTAINED_RATE)

        assert burst_rate == expected_burst
        assert sustained_rate == expected_sustained


class TestLLMGatewayPermissions(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.id}/llm_gateway"

    @parameterized.expand(
        [
            ("task:write", "v1/messages/", True),
            ("task:write", "v1/chat/completions/", True),
            ("task:read", "v1/messages/", False),
            ("task:read", "v1/chat/completions/", False),
            ("other:write", "v1/messages/", False),
            ("other:write", "v1/chat/completions/", False),
            ("*", "v1/messages/", True),
            ("*", "v1/chat/completions/", True),
        ]
    )
    @patch("posthog.api.llm_gateway.http.asyncio.run")
    @patch("posthog.api.llm_gateway.http.litellm.completion")
    @patch("posthog.api.llm_gateway.http.litellm.anthropic_messages")
    def test_api_key_scope_permissions(
        self,
        scope,
        endpoint,
        should_have_access,
        _mock_anthropic,
        _mock_completion,
        _mock_asyncio,
    ):
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {"id": "test", "choices": []}
        _mock_asyncio.return_value = mock_response
        _mock_completion.return_value = mock_response

        api_key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label=f"Test API Key - {scope}",
            secure_value=hash_key_value(api_key_value),
            scopes=[scope],
        )

        self.client.logout()

        payload = (
            {
                "model": "claude-3-5-haiku-20241022",
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 10,
            }
            if "messages" in endpoint
            else {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}]}
        )

        response = self.client.post(
            f"{self.base_url}/{endpoint}",
            payload,
            format="json",
            headers={"authorization": f"Bearer {api_key_value}"},
        )

        if should_have_access:
            assert response.status_code != status.HTTP_403_FORBIDDEN, f"Expected access but got 403 for {scope} on {endpoint}"
        else:
            assert response.status_code == status.HTTP_403_FORBIDDEN, f"Expected 403 but got {response.status_code} for {scope} on {endpoint}"
