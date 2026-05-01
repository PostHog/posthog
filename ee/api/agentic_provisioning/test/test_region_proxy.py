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
    _should_proxy_bearer_lookup,
    _should_proxy_body_region,
    _should_proxy_token_lookup,
)
from ee.api.agentic_provisioning.test.base import ProvisioningTestBase

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


class TestShouldProxyBearerLookup(BaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()

    def _make_request_with_bearer(self, token: str | None):
        kwargs = {}
        if token is not None:
            kwargs["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        raw = factory.post("/", data={}, format="json", **kwargs)
        return Request(raw, parsers=[JSONParser()])

    @patch("ee.api.agentic_provisioning.region_proxy.find_oauth_access_token", return_value=None)
    def test_proxies_when_token_not_in_db(self, mock_find):
        request = self._make_request_with_bearer("unknown_token")
        assert _should_proxy_bearer_lookup(request, "US") is True
        mock_find.assert_called_once_with("unknown_token")

    @patch("ee.api.agentic_provisioning.region_proxy.find_oauth_access_token")
    def test_skips_when_token_in_db(self, mock_find):
        mock_find.return_value = MagicMock()
        request = self._make_request_with_bearer("known_token")
        assert _should_proxy_bearer_lookup(request, "US") is False

    def test_skips_when_no_authorization_header(self):
        request = self._make_request_with_bearer(None)
        assert _should_proxy_bearer_lookup(request, "US") is False

    def test_skips_when_non_bearer_scheme(self):
        raw = factory.post("/", data={}, format="json", HTTP_AUTHORIZATION="Basic abc123")
        request = Request(raw, parsers=[JSONParser()])
        assert _should_proxy_bearer_lookup(request, "US") is False

    def test_skips_when_empty_bearer(self):
        request = self._make_request_with_bearer("")
        assert _should_proxy_bearer_lookup(request, "US") is False

    @patch("ee.api.agentic_provisioning.region_proxy.find_oauth_access_token")
    def test_caches_existence_result(self, mock_find):
        mock_find.return_value = MagicMock()
        request = self._make_request_with_bearer("cacheable_token")

        assert _should_proxy_bearer_lookup(request, "US") is False
        assert _should_proxy_bearer_lookup(request, "US") is False

        mock_find.assert_called_once()

    @patch("ee.api.agentic_provisioning.region_proxy.find_oauth_access_token")
    def test_caches_non_existence_result(self, mock_find):
        mock_find.return_value = None
        request = self._make_request_with_bearer("unknown_cacheable_token")

        assert _should_proxy_bearer_lookup(request, "US") is True
        assert _should_proxy_bearer_lookup(request, "US") is True

        mock_find.assert_called_once()

    def test_different_tokens_have_independent_cache(self):
        with patch("ee.api.agentic_provisioning.region_proxy.find_oauth_access_token") as mock_find:
            mock_find.side_effect = [MagicMock(), None]
            req_known = self._make_request_with_bearer("token_a")
            req_unknown = self._make_request_with_bearer("token_b")
            assert _should_proxy_bearer_lookup(req_known, "US") is False
            assert _should_proxy_bearer_lookup(req_unknown, "US") is True


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


class TestDecoratorIntegration(ProvisioningTestBase):
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_hmac_failure_returns_401_without_proxying(self):
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={"email": "test@example.com"},
            content_type="application/json",
            headers={"api-version": "0.1d"},
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


class TestBearerLookupDecoratorCoverage(ProvisioningTestBase):
    """Confirms every bearer-auth agentic endpoint proxies unknown tokens to the other region
    and handles known tokens locally."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self._local_token = self._get_bearer_token()

    def _resource_endpoints(self) -> list[tuple[str, str, str]]:
        return [
            ("POST", f"/api/agentic/provisioning/resources", ""),
            ("GET", f"/api/agentic/provisioning/resources/{self.team.id}", ""),
            ("POST", f"/api/agentic/provisioning/resources/{self.team.id}/rotate_credentials", ""),
            ("POST", f"/api/agentic/provisioning/resources/{self.team.id}/update_service", "free"),
            ("POST", f"/api/agentic/provisioning/resources/{self.team.id}/remove", ""),
            ("POST", f"/api/agentic/provisioning/deep_links", ""),
        ]

    def _call(self, method: str, url: str, token: str, extra: str):
        data = {}
        if "update_service" in url:
            data = {"service_id": extra}
        if "deep_links" in url:
            data = {"purpose": "dashboard"}

        if method == "GET":
            return self._get_signed_with_bearer(url, token=token)
        return self._post_signed_with_bearer(url, data=data, token=token)

    @override_settings(CLOUD_DEPLOYMENT="US")
    @patch("ee.api.agentic_provisioning.region_proxy._proxy_to_region")
    def test_unknown_bearer_token_is_proxied_on_every_endpoint(self, mock_proxy):
        mock_proxy.return_value = Response({"status": "ok"}, status=200)

        for method, url, extra in self._resource_endpoints():
            mock_proxy.reset_mock()
            cache.clear()
            self._call(method, url, "totally_unknown_token", extra)
            assert mock_proxy.called, f"{method} {url} should have proxied unknown bearer to other region"

    @override_settings(CLOUD_DEPLOYMENT="US")
    @patch("ee.api.agentic_provisioning.region_proxy._proxy_to_region")
    def test_known_bearer_token_is_not_proxied(self, mock_proxy):
        for method, url, extra in self._resource_endpoints():
            mock_proxy.reset_mock()
            cache.clear()
            # A fresh token per iteration — the /remove handler revokes the token
            # when scope becomes empty, so one call can invalidate the next.
            token = self._get_bearer_token()
            self._call(method, url, token, extra)
            assert not mock_proxy.called, f"{method} {url} should not proxy for a locally valid bearer token"


class TestDecoratorCoverageContract(BaseTest):
    """Catches forgotten `@region_proxy` decorators on bearer-auth endpoints.

    If you add a new endpoint that accepts a bearer access token, either decorate it
    with `region_proxy(strategy="bearer_lookup")` or add it to the allowlist here
    with a written reason."""

    REGION_AWARE_ENDPOINTS = {
        "provisioning_resources_create": "bearer_lookup",
        "provisioning_resource_detail": "bearer_lookup",
        "provisioning_rotate_credentials": "bearer_lookup",
        "provisioning_update_service": "bearer_lookup",
        "provisioning_resource_remove": "bearer_lookup",
        "deep_links": "bearer_lookup",
        "account_requests": "body_region",
        "oauth_token": "token_lookup",
    }

    def test_all_region_aware_endpoints_have_proxy_decorator(self):
        from ee.api.agentic_provisioning import views
        from ee.api.agentic_provisioning.region_proxy import REGION_PROXY_REGISTRY

        for view_name, expected_strategy in self.REGION_AWARE_ENDPOINTS.items():
            assert hasattr(views, view_name), f"View {view_name} is missing from views.py"
            qualname = (
                getattr(views, view_name).__qualname__
                if hasattr(getattr(views, view_name), "__qualname__")
                else view_name
            )
            registered_strategy = REGION_PROXY_REGISTRY.get(qualname) or REGION_PROXY_REGISTRY.get(view_name)
            assert registered_strategy == expected_strategy, (
                f"{view_name} must be decorated with @region_proxy(strategy={expected_strategy!r}) "
                f"(registry has: {registered_strategy!r})"
            )


class TestCrossRegionLoopback(ProvisioningTestBase):
    """In-process E2E: mock the outbound HTTPS call inside _proxy_to_region so it re-enters
    this Django process with CLOUD_DEPLOYMENT flipped. Proves path, body, headers, and the
    response all round-trip correctly through a real US → EU → US loop."""

    def _loopback_other_region(self, other_region: str):
        """Build a mock side_effect that re-dispatches the proxied request via the Django
        test client with CLOUD_DEPLOYMENT set to `other_region`."""
        from urllib.parse import urlparse

        from django.test import Client

        captured: dict = {}

        def side_effect(method, url, headers=None, data=None, timeout=None):
            parsed = urlparse(url)
            path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
            wsgi_headers = {}
            for key, value in (headers or {}).items():
                if key.lower() == "host":
                    continue
                wsgi_headers[f"HTTP_{key.upper().replace('-', '_')}"] = value

            captured["path"] = path
            captured["host"] = (headers or {}).get("Host")
            captured["body_bytes"] = data
            captured["method"] = method

            client = Client()
            with override_settings(CLOUD_DEPLOYMENT=other_region):
                response = client.generic(
                    method,
                    path,
                    data=data or b"",
                    content_type=(headers or {}).get("Content-Type", "application/json"),
                    **wsgi_headers,
                )

            fake = MagicMock()
            fake.status_code = response.status_code
            fake.content = response.content
            fake.headers = {"content-type": response.get("Content-Type", "application/json")}
            try:
                fake.json.return_value = response.json() if response.content else {}
            except ValueError:
                fake.json.side_effect = ValueError("no json")
            return fake

        return side_effect, captured

    @override_settings(CLOUD_DEPLOYMENT="US")
    @patch("ee.api.agentic_provisioning.region_proxy.requests.request")
    def test_account_request_loops_us_to_eu_and_back(self, mock_request):
        """account_requests with region=EU on the US instance should:
        1. Hit US's account_requests handler
        2. Trigger body_region proxy to EU
        3. EU creates the user and returns an oauth code
        4. US relays the EU response verbatim to the caller"""
        side_effect, captured = self._loopback_other_region("EU")
        mock_request.side_effect = side_effect

        payload = {
            "email": "loopback-eu-user@example.com",
            "configuration": {"region": "EU"},
            "scopes": ["query:read"],
            "orchestrator": {"type": "stripe", "stripe": {"account": "acct_eu_loop"}},
        }

        res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)

        assert mock_request.called, "US instance should have proxied to EU"
        assert captured["host"] == "eu.posthog.com"
        assert captured["path"] == "/api/agentic/provisioning/account_requests"
        assert captured["method"] == "POST"
        assert b"loopback-eu-user@example.com" in captured["body_bytes"], (
            "body should be forwarded intact so EU sees the email"
        )

        assert res.status_code == 200
        body = res.json()
        assert body["type"] == "oauth"
        assert body["oauth"]["code"], "EU-issued auth code should surface back through US"

    @override_settings(CLOUD_DEPLOYMENT="US")
    @patch("ee.api.agentic_provisioning.region_proxy.requests.request")
    def test_bearer_request_loops_us_to_eu_when_token_unknown_locally(self, mock_request):
        """A bearer-auth resource call with a token that doesn't exist in US's DB should
        be proxied to EU, which may or may not know the token. We assert the proxy fired
        with the bearer preserved and the downstream status is relayed."""
        side_effect, captured = self._loopback_other_region("EU")
        mock_request.side_effect = side_effect

        unknown_token = "pha_totally_bogus_token_not_in_db"
        res = self._get_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}",
            token=unknown_token,
        )

        assert mock_request.called, "US should proxy bearer-auth resource call for unknown token"
        assert captured["host"] == "eu.posthog.com"
        assert captured["path"] == f"/api/agentic/provisioning/resources/{self.team.id}"
        forwarded_auth = [
            v for k, v in mock_request.call_args.kwargs["headers"].items() if k.lower() == "authorization"
        ]
        assert forwarded_auth == [f"Bearer {unknown_token}"], "bearer header must round-trip unchanged"

        assert res.status_code in (401, 403), "EU also doesn't know this token, should reject"

    @override_settings(CLOUD_DEPLOYMENT="US")
    @patch("ee.api.agentic_provisioning.region_proxy.requests.request")
    def test_proxy_loop_header_prevents_infinite_recursion(self, mock_request):
        """If EU ever sends a request back to US with the loop header, US must process
        locally instead of re-proxying."""
        from urllib.parse import urlparse

        from django.test import Client

        call_count = {"n": 0}

        def side_effect(method, url, headers=None, data=None, timeout=None):
            call_count["n"] += 1
            parsed = urlparse(url)
            wsgi_headers = {}
            for key, value in (headers or {}).items():
                if key.lower() == "host":
                    continue
                wsgi_headers[f"HTTP_{key.upper().replace('-', '_')}"] = value
            client = Client()
            with override_settings(CLOUD_DEPLOYMENT="EU"):
                response = client.generic(
                    method,
                    parsed.path,
                    data=data or b"",
                    content_type=(headers or {}).get("Content-Type", "application/json"),
                    **wsgi_headers,
                )
            fake = MagicMock()
            fake.status_code = response.status_code
            fake.content = response.content
            fake.headers = {"content-type": response.get("Content-Type", "application/json")}
            fake.json.return_value = response.json() if response.content else {}
            return fake

        mock_request.side_effect = side_effect

        payload = {
            "email": "loop-guard@example.com",
            "configuration": {"region": "EU"},
            "scopes": ["query:read"],
            "orchestrator": {"type": "stripe", "stripe": {"account": "acct_loop_guard"}},
        }
        self._post_signed("/api/agentic/provisioning/account_requests", data=payload)

        assert call_count["n"] == 1, (
            f"proxy should fire exactly once (US→EU); got {call_count['n']} — loop header not respected"
        )
