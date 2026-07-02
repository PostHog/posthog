from typing import get_args

import pytest
from unittest.mock import patch

from posthog.llm.gateway_client import Product, get_async_anthropic_gateway_client, get_async_llm_client, get_llm_client


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
