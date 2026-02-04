from typing import get_args

import pytest
from unittest.mock import patch

from posthog.llm.gateway_client import Product, get_llm_client


class TestGetLlmClient:
    @pytest.mark.parametrize("product", get_args(Product))
    def test_valid_products(self, product: str):
        assert product in get_args(Product)

    @patch("posthog.llm.gateway_client.settings")
    def test_raises_when_gateway_url_missing(self, mock_settings):
        mock_settings.LLM_GATEWAY_URL = ""
        mock_settings.LLM_GATEWAY_API_KEY = "test-key"

        with pytest.raises(ValueError, match="LLM_GATEWAY_URL and LLM_GATEWAY_API_KEY must be configured"):
            get_llm_client()

    @patch("posthog.llm.gateway_client.settings")
    def test_raises_when_gateway_api_key_missing(self, mock_settings):
        mock_settings.LLM_GATEWAY_URL = "http://gateway:8080"
        mock_settings.LLM_GATEWAY_API_KEY = ""

        with pytest.raises(ValueError, match="LLM_GATEWAY_URL and LLM_GATEWAY_API_KEY must be configured"):
            get_llm_client()

    @patch("posthog.llm.gateway_client.settings")
    def test_returns_client_with_correct_base_url(self, mock_settings):
        mock_settings.LLM_GATEWAY_URL = "http://gateway:8080"
        mock_settings.LLM_GATEWAY_API_KEY = "test-key"

        client = get_llm_client()

        assert str(client.base_url) == "http://gateway:8080/django/v1/"
        assert client.api_key == "test-key"

    @pytest.mark.parametrize(
        "product,expected_path",
        [
            ("django", "/django/v1/"),
            ("llm_gateway", "/llm_gateway/v1/"),
            ("twig", "/twig/v1/"),
            ("wizard", "/wizard/v1/"),
        ],
    )
    @patch("posthog.llm.gateway_client.settings")
    def test_product_in_base_url(self, mock_settings, product: Product, expected_path: str):
        mock_settings.LLM_GATEWAY_URL = "http://gateway:8080"
        mock_settings.LLM_GATEWAY_API_KEY = "test-key"

        client = get_llm_client(product=product)

        assert expected_path in str(client.base_url)

    @patch("posthog.llm.gateway_client.settings")
    def test_strips_trailing_slash_from_gateway_url(self, mock_settings):
        mock_settings.LLM_GATEWAY_URL = "http://gateway:8080/"
        mock_settings.LLM_GATEWAY_API_KEY = "test-key"

        client = get_llm_client()

        assert str(client.base_url) == "http://gateway:8080/django/v1/"
