import os

import pytest
from posthog.test.base import APIBaseTest

from rest_framework import status

SKIP_IF_NO_ANTHROPIC_KEY = pytest.mark.skipif(
    "ANTHROPIC_API_KEY" not in os.environ,
    reason="ANTHROPIC_API_KEY not set in environment",
)

SKIP_IF_NO_OPENAI_KEY = pytest.mark.skipif(
    "OPENAI_API_KEY" not in os.environ,
    reason="OPENAI_API_KEY not set in environment",
)


@SKIP_IF_NO_ANTHROPIC_KEY
class TestAnthropicIntegration(APIBaseTest):
    """
    Integration tests for Anthropic Messages API.
    These tests make real API calls and only run if ANTHROPIC_API_KEY is set.
    """

    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.id}/llm_gateway"

    def test_anthropic_simple_message(self):
        response = self.client.post(
            f"{self.base_url}/v1/messages/",
            data={
                "model": "claude-sonnet-4-20250514",
                "messages": [{"role": "user", "content": "Say 'test successful' and nothing else"}],
                "max_tokens": 100,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "id" in data
        assert data["type"] == "message"
        assert data["role"] == "assistant"
        assert "content" in data
        assert "usage" in data
        assert data["usage"]["input_tokens"] > 0
        assert data["usage"]["output_tokens"] > 0

    def test_anthropic_with_system_prompt(self):
        response = self.client.post(
            f"{self.base_url}/v1/messages/",
            data={
                "model": "claude-sonnet-4-20250514",
                "messages": [{"role": "user", "content": "What are you?"}],
                "max_tokens": 100,
                "system": "You are a test assistant. Always respond with 'I am a test'.",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["type"] == "message"
        assert "content" in data

    def test_anthropic_with_temperature(self):
        response = self.client.post(
            f"{self.base_url}/v1/messages/",
            data={
                "model": "claude-sonnet-4-20250514",
                "messages": [{"role": "user", "content": "Say hello"}],
                "max_tokens": 50,
                "temperature": 0.5,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["type"] == "message"

    def test_anthropic_streaming(self):
        response = self.client.post(
            f"{self.base_url}/v1/messages/",
            data={
                "model": "claude-sonnet-4-20250514",
                "messages": [{"role": "user", "content": "Count to 3"}],
                "max_tokens": 100,
                "stream": True,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response["Content-Type"] == "text/event-stream"

    def test_anthropic_with_stop_sequence(self):
        response = self.client.post(
            f"{self.base_url}/v1/messages/",
            data={
                "model": "claude-sonnet-4-20250514",
                "messages": [{"role": "user", "content": "Count: 1, 2, 3, 4, 5"}],
                "max_tokens": 100,
                "stop_sequences": ["3"],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "stop_reason" in data

    def test_anthropic_invalid_model(self):
        response = self.client.post(
            f"{self.base_url}/v1/messages/",
            data={
                "model": "invalid-model-12345",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 100,
            },
            format="json",
        )

        assert response.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_500_INTERNAL_SERVER_ERROR]
        assert "error" in response.json()


@SKIP_IF_NO_OPENAI_KEY
class TestOpenAIIntegration(APIBaseTest):
    """
    Integration tests for OpenAI Chat Completions API.
    These tests make real API calls and only run if OPENAI_API_KEY is set.
    """

    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.id}/llm_gateway"

    def test_openai_simple_completion(self):
        response = self.client.post(
            f"{self.base_url}/v1/chat/completions/",
            data={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Say 'test successful' and nothing else"}],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "id" in data
        assert data["object"] == "chat.completion"
        assert "choices" in data
        assert len(data["choices"]) > 0
        assert "usage" in data
        assert data["usage"]["prompt_tokens"] > 0
        assert data["usage"]["completion_tokens"] > 0

    def test_openai_with_system_message(self):
        response = self.client.post(
            f"{self.base_url}/v1/chat/completions/",
            data={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant that always says 'test'."},
                    {"role": "user", "content": "Hello"},
                ],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["object"] == "chat.completion"

    def test_openai_with_temperature(self):
        response = self.client.post(
            f"{self.base_url}/v1/chat/completions/",
            data={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Say hello"}],
                "temperature": 0.7,
                "max_tokens": 50,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["object"] == "chat.completion"

    def test_openai_streaming(self):
        response = self.client.post(
            f"{self.base_url}/v1/chat/completions/",
            data={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Count to 3"}],
                "stream": True,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response["Content-Type"] == "text/event-stream"

    def test_openai_with_max_tokens(self):
        response = self.client.post(
            f"{self.base_url}/v1/chat/completions/",
            data={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Write a long story"}],
                "max_tokens": 10,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["choices"][0]["finish_reason"] == "length"

    def test_openai_with_stop_sequence(self):
        response = self.client.post(
            f"{self.base_url}/v1/chat/completions/",
            data={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Count: 1, 2, 3"}],
                "stop": ["3"],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "choices" in data

    def test_openai_with_seed(self):
        response = self.client.post(
            f"{self.base_url}/v1/chat/completions/",
            data={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Say hello"}],
                "seed": 42,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "system_fingerprint" in data

    def test_openai_invalid_model(self):
        response = self.client.post(
            f"{self.base_url}/v1/chat/completions/",
            data={
                "model": "invalid-model-12345",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            format="json",
        )

        assert response.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_500_INTERNAL_SERVER_ERROR]
        assert "error" in response.json()
