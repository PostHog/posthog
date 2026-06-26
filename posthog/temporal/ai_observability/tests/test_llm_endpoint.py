"""Tests for clustering labeling client construction (ai-gateway vs direct OpenAI)."""

import json

import pytest
from unittest.mock import patch

from django.test import override_settings

from posthog.temporal.ai_observability.llm_endpoint import build_langchain_chat_client

GATEWAY_URL = "https://gateway.example/v1"
GATEWAY_KEY = "phs_project_secret"


class TestBuildOpenAIChatClient:
    @pytest.mark.parametrize(
        "gateway_url,gateway_key,expected_base,expected_key,custom_http_client",
        [
            (GATEWAY_URL, GATEWAY_KEY, GATEWAY_URL, GATEWAY_KEY, True),
            (None, None, None, "sk-direct", False),
        ],
    )
    def test_routing_resolves_endpoint_and_credentials(
        self, gateway_url, gateway_key, expected_base, expected_key, custom_http_client
    ):
        with (
            override_settings(DEBUG=True, AI_GATEWAY_URL=gateway_url, AI_GATEWAY_API_KEY=gateway_key),
            patch.dict("os.environ", {"OPENAI_API_KEY": "sk-direct"}, clear=False),
        ):
            client = build_langchain_chat_client("gpt-5.4", 600.0)

        assert client.openai_api_base == expected_base
        api_key = client.openai_api_key
        assert api_key is not None
        assert api_key.get_secret_value() == expected_key
        # Gateway mode injects a trust_env=False http client; direct mode uses the SDK default.
        if custom_http_client:
            assert client.http_client is not None
            assert client.http_async_client is not None
        else:
            assert client.http_client is None

    @pytest.mark.parametrize(
        "gateway_url,gateway_key,reason",
        [
            (GATEWAY_URL, None, "must be set together"),
            (None, GATEWAY_KEY, "must be set together"),
            ("https://gateway.example", GATEWAY_KEY, "OpenAI base path"),
        ],
    )
    def test_misconfigured_gateway_falls_back_to_direct_and_logs(self, gateway_url, gateway_key, reason):
        # Radu review: a half-applied / malformed gateway config falls back to the direct provider
        # rather than failing the call, and logs loudly so a broken rollout config is visible.
        with (
            override_settings(DEBUG=True, AI_GATEWAY_URL=gateway_url, AI_GATEWAY_API_KEY=gateway_key),
            patch.dict("os.environ", {"OPENAI_API_KEY": "sk-direct"}, clear=False),
            patch("posthog.temporal.ai_observability.llm_endpoint.logger") as mock_logger,
        ):
            client = build_langchain_chat_client("gpt-5.4", 600.0)

        assert client.openai_api_base is None
        api_key = client.openai_api_key
        assert api_key is not None
        assert api_key.get_secret_value() == "sk-direct"
        mock_logger.warning.assert_called_once()
        assert reason in str(mock_logger.warning.call_args)

    @override_settings(DEBUG=True, AI_GATEWAY_URL=GATEWAY_URL, AI_GATEWAY_API_KEY=GATEWAY_KEY)
    def test_gateway_mode_tags_ai_product_via_posthog_properties_header(self):
        with patch("posthog.temporal.ai_observability.llm_endpoint.ChatOpenAI") as mock_chat:
            build_langchain_chat_client("gpt-5.4", 600.0, ai_product="aio_clustering")

        assert mock_chat.call_args.kwargs["default_headers"] == {
            "X-PostHog-Properties": json.dumps({"ai_product": "aio_clustering"})
        }

    @override_settings(DEBUG=True, AI_GATEWAY_URL=GATEWAY_URL, AI_GATEWAY_API_KEY=GATEWAY_KEY)
    def test_gateway_mode_without_ai_product_omits_header(self):
        with patch("posthog.temporal.ai_observability.llm_endpoint.ChatOpenAI") as mock_chat:
            build_langchain_chat_client("gpt-5.4", 600.0)

        assert mock_chat.call_args.kwargs["default_headers"] is None
