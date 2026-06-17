"""Tests for clustering labeling client construction (ai-gateway vs direct OpenAI)."""

import pytest
from unittest.mock import patch

from django.test import override_settings

from posthog.temporal.ai_observability.llm_endpoint import build_openai_chat_client

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
            client = build_openai_chat_client("gpt-5.4", 600.0)

        assert client.openai_api_base == expected_base
        assert client.openai_api_key.get_secret_value() == expected_key
        # Gateway mode injects a trust_env=False http client; direct mode uses the SDK default.
        if custom_http_client:
            assert client.http_client is not None
            assert client.http_async_client is not None
        else:
            assert client.http_client is None

    @pytest.mark.parametrize(
        "gateway_url,gateway_key",
        [
            (GATEWAY_URL, None),
            (None, GATEWAY_KEY),
        ],
    )
    def test_half_set_gateway_config_raises(self, gateway_url, gateway_key):
        with (
            override_settings(DEBUG=True, AI_GATEWAY_URL=gateway_url, AI_GATEWAY_API_KEY=gateway_key),
            patch.dict("os.environ", {"OPENAI_API_KEY": "sk-direct"}, clear=False),
        ):
            with pytest.raises(Exception, match="must be set together"):
                build_openai_chat_client("gpt-5.4", 600.0)

    @override_settings(DEBUG=True, AI_GATEWAY_URL="https://gateway.example", AI_GATEWAY_API_KEY=GATEWAY_KEY)
    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-direct"}, clear=False)
    def test_gateway_url_missing_v1_path_raises(self):
        with pytest.raises(Exception, match="OpenAI base path"):
            build_openai_chat_client("gpt-5.4", 600.0)
