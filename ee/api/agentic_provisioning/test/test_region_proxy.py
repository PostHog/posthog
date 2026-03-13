from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings

from rest_framework.parsers import JSONParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from ee.api.agentic_provisioning import AUTH_CODE_CACHE_PREFIX
from ee.api.agentic_provisioning.region_proxy import (
    _proxy_to_region,
    _should_proxy_body_region,
    _should_proxy_token_lookup,
)
from ee.api.agentic_provisioning.test.base import StripeProvisioningTestBase

factory = APIRequestFactory()


def _make_drf_request(data=None):
    raw = factory.post("/", data=data or {}, format="json")
    return Request(raw, parsers=[JSONParser()])


class TestShouldProxyBodyRegion(BaseTest):
    def test_proxies_on_region_mismatch(self):
        request = _make_drf_request({"configuration": {"region": "EU"}})
        assert _should_proxy_body_region(request, "US") is True

    def test_skips_on_region_match(self):
        request = _make_drf_request({"configuration": {"region": "US"}})
        assert _should_proxy_body_region(request, "US") is False

    def test_defaults_to_us_when_no_region(self):
        request = _make_drf_request({"configuration": {}})
        assert _should_proxy_body_region(request, "US") is False
        request2 = _make_drf_request({"configuration": {}})
        assert _should_proxy_body_region(request2, "EU") is True

    def test_defaults_to_us_when_no_configuration(self):
        request = _make_drf_request({})
        assert _should_proxy_body_region(request, "US") is False

    def test_case_insensitive(self):
        request = _make_drf_request({"configuration": {"region": "eu"}})
        assert _should_proxy_body_region(request, "US") is True

        request2 = _make_drf_request({"configuration": {"region": "us"}})
        assert _should_proxy_body_region(request2, "US") is False


class TestShouldProxyTokenLookup(BaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()

    def test_proxies_when_auth_code_not_in_cache(self):
        request = _make_drf_request({"grant_type": "authorization_code", "code": "unknown_code"})
        assert _should_proxy_token_lookup(request, "US") is True

    def test_skips_when_auth_code_in_cache(self):
        cache.set(f"{AUTH_CODE_CACHE_PREFIX}known_code", {"user_id": 1}, timeout=300)
        request = _make_drf_request({"grant_type": "authorization_code", "code": "known_code"})
        assert _should_proxy_token_lookup(request, "US") is False

    def test_skips_when_empty_code(self):
        request = _make_drf_request({"grant_type": "authorization_code", "code": ""})
        assert _should_proxy_token_lookup(request, "US") is False

    @patch("ee.api.agentic_provisioning.region_proxy.find_oauth_refresh_token", return_value=None)
    def test_proxies_when_refresh_token_not_in_db(self, mock_find):
        request = _make_drf_request({"grant_type": "refresh_token", "refresh_token": "unknown_token"})
        assert _should_proxy_token_lookup(request, "US") is True

    @patch("ee.api.agentic_provisioning.region_proxy.find_oauth_refresh_token")
    def test_skips_when_refresh_token_in_db(self, mock_find):
        mock_find.return_value = MagicMock()
        request = _make_drf_request({"grant_type": "refresh_token", "refresh_token": "known_token"})
        assert _should_proxy_token_lookup(request, "US") is False

    def test_skips_unsupported_grant_type(self):
        request = _make_drf_request({"grant_type": "client_credentials"})
        assert _should_proxy_token_lookup(request, "US") is False


class TestProxyHeaderAllowlist(BaseTest):
    @patch("ee.api.agentic_provisioning.region_proxy.requests")
    def test_strips_cookies_and_forwarded_headers(self, mock_requests):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"status": "ok"}'
        mock_response.json.return_value = {"status": "ok"}
        mock_requests.request.return_value = mock_response

        raw = factory.post(
            "/api/agentic/provisioning/health",
            data={},
            format="json",
            HTTP_COOKIE="sessionid=secret123",
            HTTP_X_FORWARDED_FOR="10.0.0.1",
            HTTP_STRIPE_SIGNATURE="t=123,v1=abc",
            HTTP_AUTHORIZATION="Bearer pha_test",
        )
        request = Request(raw, parsers=[JSONParser()])

        _proxy_to_region(request, "eu.posthog.com")

        call_kwargs = mock_requests.request.call_args
        forwarded_headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        header_keys_lower = {k.lower() for k in forwarded_headers}

        assert "cookie" not in header_keys_lower
        assert "x-forwarded-for" not in header_keys_lower
        assert "host" in header_keys_lower
        assert forwarded_headers["Host"] == "eu.posthog.com"


class TestDecoratorIntegration(StripeProvisioningTestBase):
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_hmac_failure_returns_401_without_proxying(self):
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={"email": "test@example.com"},
            content_type="application/json",
            HTTP_API_VERSION="0.1d",
        )
        assert res.status_code == 401

    @override_settings(CLOUD_DEPLOYMENT="US")
    @patch("ee.api.agentic_provisioning.region_proxy._proxy_to_region")
    def test_proxy_success_returns_proxied_response(self, mock_proxy):
        mock_proxy.return_value = Response({"type": "oauth", "oauth": {"code": "abc"}})
        payload = {"email": "test@example.com", "configuration": {"region": "EU"}}
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        assert mock_proxy.called
        assert res.status_code == 200

    @override_settings(CLOUD_DEPLOYMENT="US")
    @patch("ee.api.agentic_provisioning.region_proxy._proxy_to_region")
    def test_body_region_proxy_failure_returns_502(self, mock_proxy):
        import requests

        mock_proxy.side_effect = requests.exceptions.ConnectionError("connection refused")
        payload = {"email": "test@example.com", "configuration": {"region": "EU"}}
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        assert res.status_code == 502
        assert res.json()["error"]["code"] == "proxy_failed"

    @override_settings(CLOUD_DEPLOYMENT=None)
    def test_dev_skips_proxy_entirely(self):
        payload = {
            "email": "devuser@example.com",
            "configuration": {"region": "EU"},
            "scopes": ["query:read"],
            "orchestrator": {"type": "stripe", "stripe": {"account": "acct_dev"}},
        }
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        assert res.status_code == 200
        assert res.json()["type"] == "oauth"

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_matching_region_no_proxy(self):
        payload = {
            "email": "ususer@example.com",
            "configuration": {"region": "US"},
            "scopes": ["query:read"],
            "orchestrator": {"type": "stripe", "stripe": {"account": "acct_us"}},
        }
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        assert res.status_code == 200
        assert res.json()["type"] == "oauth"
