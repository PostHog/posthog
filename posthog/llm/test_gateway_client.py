import json
from typing import get_args

import pytest
from unittest.mock import patch

from django.test import override_settings

from posthog.llm.gateway_client import (
    Product,
    build_async_openai_client,
    build_openai_client,
    get_async_anthropic_gateway_client,
    get_async_llm_client,
    get_llm_client,
    resolve_ai_gateway_config,
)

AI_GATEWAY_URL = "https://ai-gateway.example/v1"
AI_GATEWAY_KEY = "phs_project_secret"


class TestGetLlmClient:
    @pytest.mark.parametrize("product", get_args(Product))
    def test_valid_products(self, product: str):
        assert product in get_args(Product)

    @patch("posthog.llm.gateway_client.settings")
    def test_raises_when_gateway_url_missing(self, mock_settings):
        mock_settings.LLM_GATEWAY_URL = ""
        mock_settings.LLM_GATEWAY_API_KEY = "test-key"

        with pytest.raises(ValueError, match="LLM_GATEWAY_URL and LLM_GATEWAY_API_KEY must be configured"):
            get_llm_client(product="django", team_id=1)

    @patch("posthog.llm.gateway_client.settings")
    def test_raises_when_gateway_api_key_missing(self, mock_settings):
        mock_settings.LLM_GATEWAY_URL = "http://gateway:8080"
        mock_settings.LLM_GATEWAY_API_KEY = ""

        with pytest.raises(ValueError, match="LLM_GATEWAY_URL and LLM_GATEWAY_API_KEY must be configured"):
            get_llm_client(product="django", team_id=1)

    @patch("posthog.llm.gateway_client.settings")
    def test_returns_client_with_correct_base_url(self, mock_settings):
        mock_settings.LLM_GATEWAY_URL = "http://gateway:8080"
        mock_settings.LLM_GATEWAY_API_KEY = "test-key"

        client = get_llm_client(product="django", team_id=1)

        assert str(client.base_url) == "http://gateway:8080/django/v1/"
        assert client.api_key == "test-key"

    @pytest.mark.parametrize(
        "product,expected_path",
        [
            ("django", "/django/v1/"),
            ("llm_gateway", "/llm_gateway/v1/"),
            ("posthog_code", "/posthog_code/v1/"),
            ("wizard", "/wizard/v1/"),
            ("signals", "/signals/v1/"),
        ],
    )
    @patch("posthog.llm.gateway_client.settings")
    def test_product_in_base_url(self, mock_settings, product: Product, expected_path: str):
        mock_settings.LLM_GATEWAY_URL = "http://gateway:8080"
        mock_settings.LLM_GATEWAY_API_KEY = "test-key"

        client = get_llm_client(product=product, team_id=1)

        assert expected_path in str(client.base_url)

    @patch("posthog.llm.gateway_client.settings")
    def test_strips_trailing_slash_from_gateway_url(self, mock_settings):
        mock_settings.LLM_GATEWAY_URL = "http://gateway:8080/"
        mock_settings.LLM_GATEWAY_API_KEY = "test-key"

        client = get_llm_client(product="django", team_id=1)

        assert str(client.base_url) == "http://gateway:8080/django/v1/"

    @patch("posthog.llm.gateway_client.settings")
    def test_attaches_team_id_default_header(self, mock_settings):
        mock_settings.LLM_GATEWAY_URL = "http://gateway:8080"
        mock_settings.LLM_GATEWAY_API_KEY = "test-key"

        client = get_llm_client(product="signals", team_id=42)

        assert client.default_headers.get("x-posthog-property-team_id") == "42"

    @patch("posthog.llm.gateway_client.settings")
    def test_async_client_attaches_team_id_default_header(self, mock_settings):
        mock_settings.LLM_GATEWAY_URL = "http://gateway:8080"
        mock_settings.LLM_GATEWAY_API_KEY = "test-key"

        client = get_async_llm_client(product="signals", team_id=42)

        assert client.default_headers.get("x-posthog-property-team_id") == "42"

    @patch("posthog.llm.gateway_client.settings")
    def test_no_team_id_header_when_team_id_omitted(self, mock_settings):
        mock_settings.LLM_GATEWAY_URL = "http://gateway:8080"
        mock_settings.LLM_GATEWAY_API_KEY = "test-key"

        client = get_llm_client(product="django")

        assert client.default_headers.get("x-posthog-property-team_id") is None

    @patch("posthog.llm.gateway_client.settings")
    def test_product_defaults_to_django(self, mock_settings):
        mock_settings.LLM_GATEWAY_URL = "http://gateway:8080"
        mock_settings.LLM_GATEWAY_API_KEY = "test-key"

        client = get_llm_client()

        assert str(client.base_url) == "http://gateway:8080/django/v1/"


class TestGetAsyncAnthropicGatewayClient:
    @patch("posthog.llm.gateway_client.settings")
    def test_raises_when_gateway_unconfigured(self, mock_settings):
        mock_settings.LLM_GATEWAY_URL = ""
        mock_settings.LLM_GATEWAY_API_KEY = "test-key"

        with pytest.raises(ValueError, match="LLM_GATEWAY_URL and LLM_GATEWAY_API_KEY must be configured"):
            get_async_anthropic_gateway_client(product="signals", team_id=1)

    @patch("posthog.llm.gateway_client.settings")
    def test_base_url_omits_v1_suffix(self, mock_settings):
        # The Anthropic SDK appends /v1/messages itself, so the base_url stops at the product.
        mock_settings.LLM_GATEWAY_URL = "http://gateway:8080/"
        mock_settings.LLM_GATEWAY_API_KEY = "test-key"

        client = get_async_anthropic_gateway_client(product="signals", team_id=1)

        assert str(client.base_url) == "http://gateway:8080/signals/"
        assert client.api_key == "test-key"

    @patch("posthog.llm.gateway_client.settings")
    def test_attaches_team_id_default_header(self, mock_settings):
        mock_settings.LLM_GATEWAY_URL = "http://gateway:8080"
        mock_settings.LLM_GATEWAY_API_KEY = "test-key"

        client = get_async_anthropic_gateway_client(product="signals", team_id=42)

        assert client.default_headers.get("x-posthog-property-team_id") == "42"

    @patch("posthog.llm.gateway_client.settings")
    def test_no_team_id_header_when_team_id_omitted(self, mock_settings):
        mock_settings.LLM_GATEWAY_URL = "http://gateway:8080"
        mock_settings.LLM_GATEWAY_API_KEY = "test-key"

        client = get_async_anthropic_gateway_client(product="signals")

        assert client.default_headers.get("x-posthog-property-team_id") is None

    @pytest.mark.parametrize(
        "use_bedrock_fallback, expected_header_value",
        [
            (True, "true"),
            (False, None),
        ],
    )
    @patch("posthog.llm.gateway_client.settings")
    def test_bedrock_fallback_header(self, mock_settings, use_bedrock_fallback: bool, expected_header_value):
        mock_settings.LLM_GATEWAY_URL = "http://gateway:8080"
        mock_settings.LLM_GATEWAY_API_KEY = "test-key"

        client = get_async_anthropic_gateway_client(
            product="signals", team_id=42, use_bedrock_fallback=use_bedrock_fallback
        )

        assert client.default_headers.get("x-posthog-use-bedrock-fallback") == expected_header_value


class TestResolveAIGatewayConfig:
    @override_settings(AI_GATEWAY_URL="", AI_GATEWAY_API_KEY="")
    def test_returns_none_when_both_unset(self):
        assert resolve_ai_gateway_config() is None

    @override_settings(AI_GATEWAY_URL=AI_GATEWAY_URL, AI_GATEWAY_API_KEY=AI_GATEWAY_KEY)
    def test_returns_pair_when_both_set(self):
        assert resolve_ai_gateway_config() == (AI_GATEWAY_URL, AI_GATEWAY_KEY)

    @pytest.mark.parametrize(
        "url,key,reason",
        [
            (AI_GATEWAY_URL, "", "must be set together"),
            ("", AI_GATEWAY_KEY, "must be set together"),
            ("https://ai-gateway.example", AI_GATEWAY_KEY, "OpenAI base path"),
        ],
    )
    def test_misconfig_falls_back_to_none_and_logs(self, url, key, reason):
        # Radu review: a misconfig logs and returns None so callers fall back, never raises.
        with (
            override_settings(AI_GATEWAY_URL=url, AI_GATEWAY_API_KEY=key),
            patch("posthog.llm.gateway_client.logger") as mock_logger,
        ):
            assert resolve_ai_gateway_config() is None

        mock_logger.warning.assert_called_once()
        assert reason in str(mock_logger.warning.call_args)


class TestBuildOpenAIClient:
    @override_settings(AI_GATEWAY_URL=AI_GATEWAY_URL, AI_GATEWAY_API_KEY=AI_GATEWAY_KEY)
    @patch("posthog.llm.gateway_client.httpx.Client")
    @patch("posthog.llm.gateway_client.OpenAI")
    def test_gateway_mode_routes_to_slugless_go_gateway_with_ai_product(self, mock_openai, mock_httpx):
        result = build_openai_client("llma_summarization", ai_product="aio_summarization")

        mock_httpx.assert_called_once_with(trust_env=False)
        mock_openai.assert_called_once_with(
            api_key=AI_GATEWAY_KEY,
            base_url=AI_GATEWAY_URL,
            default_headers={"X-PostHog-Properties": json.dumps({"ai_product": "aio_summarization"})},
            http_client=mock_httpx.return_value,
        )
        assert result is mock_openai.return_value

    @override_settings(AI_GATEWAY_URL="", AI_GATEWAY_API_KEY="")
    @patch("posthog.llm.gateway_client.get_llm_client")
    def test_falls_back_to_python_gateway_when_unset(self, mock_get_llm_client):
        result = build_openai_client("llma_summarization", ai_product="aio_summarization")

        mock_get_llm_client.assert_called_once_with("llma_summarization")
        assert result is mock_get_llm_client.return_value


class TestBuildAsyncOpenAIClient:
    @override_settings(AI_GATEWAY_URL=AI_GATEWAY_URL, AI_GATEWAY_API_KEY=AI_GATEWAY_KEY)
    @patch("posthog.llm.gateway_client.httpx.AsyncClient")
    @patch("posthog.llm.gateway_client.AsyncOpenAI")
    def test_gateway_mode_routes_to_slugless_go_gateway_with_ai_product(self, mock_async_openai, mock_httpx):
        result = build_async_openai_client("llma_eval_summary", ai_product="aio_eval_summary")

        mock_httpx.assert_called_once_with(trust_env=False)
        mock_async_openai.assert_called_once_with(
            api_key=AI_GATEWAY_KEY,
            base_url=AI_GATEWAY_URL,
            default_headers={"X-PostHog-Properties": json.dumps({"ai_product": "aio_eval_summary"})},
            http_client=mock_httpx.return_value,
        )
        assert result is mock_async_openai.return_value

    @override_settings(AI_GATEWAY_URL="", AI_GATEWAY_API_KEY="")
    @patch("posthog.llm.gateway_client.get_async_llm_client")
    def test_falls_back_to_python_async_gateway_when_unset(self, mock_get_async):
        result = build_async_openai_client("llma_eval_summary", ai_product="aio_eval_summary")

        mock_get_async.assert_called_once_with("llma_eval_summary")
        assert result is mock_get_async.return_value
