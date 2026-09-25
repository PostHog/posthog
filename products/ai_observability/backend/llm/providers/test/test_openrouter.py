import pytest
from unittest.mock import MagicMock, patch

import httpx
from parameterized import parameterized

from products.ai_observability.backend.llm.errors import (
    ModelNotFoundError,
    RateLimitError,
    StructuredOutputParseError,
    UnsupportedModelError,
)
from products.ai_observability.backend.llm.providers.openai import OpenAIAdapter
from products.ai_observability.backend.llm.providers.openrouter import (
    OPENROUTER_HEADERS,
    OpenRouterAdapter,
    _non_chat_model_ids,
)


class TestOpenRouterValidateKey:
    @parameterized.expand(
        [
            ("valid_key_returns_ok", 200, "ok", None),
            ("invalid_key_returns_invalid", 401, "invalid", "Invalid API key"),
            ("server_error_returns_error", 500, "error", "Unexpected response status: 500"),
        ]
    )
    def test_validate_key_status_codes(self, _name, status_code, expected_state, expected_message):
        mock_response = MagicMock()
        mock_response.status_code = status_code

        with patch("products.ai_observability.backend.llm.providers.openrouter.httpx.get", return_value=mock_response):
            state, message = OpenRouterAdapter.validate_key("sk-or-test-key")

        assert state == expected_state
        assert message == expected_message

    def test_validate_key_timeout_returns_error(self):
        with patch(
            "products.ai_observability.backend.llm.providers.openrouter.httpx.get",
            side_effect=httpx.TimeoutException("timeout"),
        ):
            state, message = OpenRouterAdapter.validate_key("sk-or-test-key")

        assert state == "error"
        assert message == "Request timed out, please try again"

    def test_validate_key_connection_error_returns_error(self):
        with patch(
            "products.ai_observability.backend.llm.providers.openrouter.httpx.get",
            side_effect=httpx.ConnectError("connection refused"),
        ):
            state, message = OpenRouterAdapter.validate_key("sk-or-test-key")

        assert state == "error"
        assert message == "Could not connect to OpenRouter"


class TestOpenRouterListModels:
    def test_list_models_without_key_returns_empty(self):
        assert OpenRouterAdapter.list_models(None) == []

    def test_list_models_with_key_returns_newest_first(self):
        mock_model_older = MagicMock()
        mock_model_older.id = "anthropic/claude-3.5-sonnet"
        mock_model_older.created = 1700000000

        mock_model_newer = MagicMock()
        mock_model_newer.id = "openai/gpt-4o"
        mock_model_newer.created = 1710000000

        mock_client = MagicMock()
        mock_client.models.list.return_value = [mock_model_older, mock_model_newer]

        with patch(
            "products.ai_observability.backend.llm.providers.openrouter.openai.OpenAI", return_value=mock_client
        ):
            models = OpenRouterAdapter.list_models("sk-or-test-key")

        assert models == ["openai/gpt-4o", "anthropic/claude-3.5-sonnet"]

    def test_list_models_error_returns_empty(self):
        with patch(
            "products.ai_observability.backend.llm.providers.openrouter.openai.OpenAI",
            side_effect=Exception("API error"),
        ):
            models = OpenRouterAdapter.list_models("sk-or-test-key")

        assert models == []


class TestOpenRouterDefaultKey:
    def test_get_api_key_raises(self):
        with pytest.raises(ValueError, match="BYOKEY-only"):
            OpenRouterAdapter.get_api_key()

    def test_get_default_api_key_raises(self):
        adapter = OpenRouterAdapter()

        with pytest.raises(ValueError, match="BYOKEY-only"):
            adapter._get_default_api_key()


class TestOpenRouterRecommendedModels:
    def test_recommended_models_returns_empty(self):
        assert OpenRouterAdapter.recommended_models() == set()


class TestOpenRouterHeaders:
    def test_openai_adapter_returns_empty_headers(self):
        adapter = OpenAIAdapter()
        assert adapter._get_default_headers() == {}

    def test_openrouter_adapter_returns_attribution_headers(self):
        adapter = OpenRouterAdapter()

        headers = adapter._get_default_headers()

        assert headers == {"HTTP-Referer": "https://posthog.com", "X-Title": "PostHog"}

    def test_list_models_passes_headers_to_client(self):
        mock_client = MagicMock()
        mock_client.models.list.return_value = []

        with patch(
            "products.ai_observability.backend.llm.providers.openrouter.openai.OpenAI", return_value=mock_client
        ) as mock_constructor:
            OpenRouterAdapter.list_models("sk-or-test-key")

        mock_constructor.assert_called_once()
        assert mock_constructor.call_args.kwargs["default_headers"] == OPENROUTER_HEADERS


class TestOpenRouterNonChatModels:
    @parameterized.expand(
        [
            (
                "not_found_on_decision_model",
                ModelNotFoundError("typesafe/jev-1.13"),
                "typesafe/jev-1.13",
                {"typesafe/jev-1.13"},
                UnsupportedModelError,
            ),
            (
                "parse_error_on_decision_model",
                StructuredOutputParseError("bad"),
                "typesafe/jev-1.13",
                {"typesafe/jev-1.13"},
                UnsupportedModelError,
            ),
            (
                "error_on_chat_model",
                ModelNotFoundError("openai/gpt-4o"),
                "openai/gpt-4o",
                {"typesafe/jev-1.13"},
                ModelNotFoundError,
            ),
            ("catalogue_unavailable", ValueError("400"), "typesafe/jev-1.13", None, ValueError),
            (
                "rate_limit_on_decision_model",
                RateLimitError("slow down"),
                "typesafe/jev-1.13",
                {"typesafe/jev-1.13"},
                RateLimitError,
            ),
        ]
    )
    def test_complete_maps_failures_of_non_chat_models(self, _name, raised, model, non_chat_ids, expected):
        request = MagicMock(model=model)
        with (
            patch.object(OpenAIAdapter, "complete", side_effect=raised),
            patch(
                "products.ai_observability.backend.llm.providers.openrouter._non_chat_model_ids",
                return_value=frozenset(non_chat_ids) if non_chat_ids is not None else None,
            ),
            pytest.raises(expected),
        ):
            OpenRouterAdapter().complete(request, "sk-or-test-key", MagicMock())

    def test_catalogue_keeps_only_models_without_text_output(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"id": "openai/gpt-4o", "architecture": {"output_modalities": ["text"]}},
                {"id": "google/image-model", "architecture": {"output_modalities": ["image", "text"]}},
                {"id": "typesafe/jev-1.13", "architecture": {"output_modalities": ["decisions"]}},
                {"id": "no-architecture/model"},
            ]
        }
        with (
            patch("products.ai_observability.backend.llm.providers.openrouter.cache.get", return_value=None),
            patch("products.ai_observability.backend.llm.providers.openrouter.cache.set"),
            patch("products.ai_observability.backend.llm.providers.openrouter.httpx.get", return_value=mock_response),
        ):
            assert _non_chat_model_ids() == frozenset({"typesafe/jev-1.13"})
