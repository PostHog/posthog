from contextlib import contextmanager

import pytest
from unittest.mock import patch

import httpx

from posthog.llm.gateway_client import GatewayAdminError, get_posthog_code_usage, reset_posthog_code_usage


@contextmanager
def _mock_gateway(handler):
    """Patch the module's httpx.Client to use a MockTransport routed to `handler`,
    while keeping real httpx request/response handling (so URL, headers, and JSON
    body are exercised exactly as in production)."""
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client  # capture before patching to avoid recursing into the patch

    def factory(**kwargs):
        return real_client(transport=transport)

    with patch("posthog.llm.gateway_client.httpx.Client", factory):
        yield


class TestGatewayAdminClient:
    @patch("posthog.llm.gateway_client.settings")
    def test_usage_raises_without_url(self, mock_settings):
        mock_settings.LLM_GATEWAY_URL = ""
        mock_settings.LLM_GATEWAY_ADMIN_SECRET = "secret"
        with pytest.raises(GatewayAdminError, match="LLM_GATEWAY_URL"):
            get_posthog_code_usage(100)

    @patch("posthog.llm.gateway_client.settings")
    def test_reset_raises_without_secret(self, mock_settings):
        mock_settings.LLM_GATEWAY_URL = "http://gateway:8080"
        mock_settings.LLM_GATEWAY_ADMIN_SECRET = ""
        with pytest.raises(GatewayAdminError, match="LLM_GATEWAY_ADMIN_SECRET"):
            reset_posthog_code_usage(100)

    @patch("posthog.llm.gateway_client.settings")
    def test_usage_builds_request_and_returns_json(self, mock_settings):
        mock_settings.LLM_GATEWAY_URL = "http://gateway:8080/"
        mock_settings.LLM_GATEWAY_ADMIN_SECRET = "secret"
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["secret"] = request.headers.get("x-llm-gateway-admin-secret")
            return httpx.Response(200, json={"user_id": "100", "product": "posthog_code", "counters": []})

        with _mock_gateway(handler):
            result = get_posthog_code_usage(100)

        assert captured["url"] == "http://gateway:8080/v1/admin/usage/100"
        assert captured["secret"] == "secret"
        assert result["product"] == "posthog_code"

    @patch("posthog.llm.gateway_client.settings")
    def test_reset_sends_flags_and_returns_json(self, mock_settings):
        mock_settings.LLM_GATEWAY_URL = "http://gateway:8080"
        mock_settings.LLM_GATEWAY_ADMIN_SECRET = "secret"
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"user_id": "100", "total_keys": 2})

        with _mock_gateway(handler):
            result = reset_posthog_code_usage(
                100, reset_cost=True, reset_request=True, reset_product_total=False, dry_run=True
            )

        assert captured["url"] == "http://gateway:8080/v1/admin/reset/100"
        assert captured["body"] == {"cost": True, "request": True, "product_total": False, "dry_run": True}
        assert result["total_keys"] == 2

    @patch("posthog.llm.gateway_client.settings")
    def test_reset_defaults_to_cost_only(self, mock_settings):
        mock_settings.LLM_GATEWAY_URL = "http://gateway:8080"
        mock_settings.LLM_GATEWAY_ADMIN_SECRET = "secret"
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"total_keys": 0})

        with _mock_gateway(handler):
            reset_posthog_code_usage(100)

        assert captured["body"] == {"cost": True, "request": False, "product_total": False, "dry_run": False}

    @patch("posthog.llm.gateway_client.settings")
    def test_http_error_propagates(self, mock_settings):
        mock_settings.LLM_GATEWAY_URL = "http://gateway:8080"
        mock_settings.LLM_GATEWAY_ADMIN_SECRET = "secret"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"detail": "boom"})

        with _mock_gateway(handler), pytest.raises(httpx.HTTPStatusError):
            get_posthog_code_usage(100)
