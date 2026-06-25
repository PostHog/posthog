import pytest
from unittest.mock import MagicMock, patch

from django.core.cache import cache as real_cache
from django.test import SimpleTestCase, override_settings

import requests

from posthog.api.oauth.mcp_resource_scopes import (
    _scopes_cache_key,
    build_oauth_mcp_consent_context,
    fetch_mcp_protected_resource_scopes,
    is_trusted_posthog_mcp_resource,
)


class TestMcpResourceScopes(SimpleTestCase):
    _MCP_RESOURCE_URL = "https://mcp.posthog.com/mcp"

    def _clear_mcp_scopes_cache(self, resource_url: str | None = None) -> None:
        real_cache.delete(_scopes_cache_key(resource_url or self._MCP_RESOURCE_URL))

    def test_is_trusted_posthog_mcp_resource_production(self):
        for host in (
            "mcp.posthog.com",
            "mcp.us.posthog.com",
            "mcp.eu.posthog.com",
            "mcp-eu.posthog.com",
        ):
            self.assertTrue(is_trusted_posthog_mcp_resource(f"https://{host}/mcp"))
            self.assertFalse(is_trusted_posthog_mcp_resource(f"http://{host}/mcp"))
        self.assertFalse(is_trusted_posthog_mcp_resource("https://evil.posthog.com/mcp"))

    @override_settings(DEBUG=True)
    def test_is_trusted_posthog_mcp_resource_local_dev(self):
        self.assertTrue(is_trusted_posthog_mcp_resource("http://localhost:8787/mcp"))
        self.assertTrue(is_trusted_posthog_mcp_resource("http://127.0.0.1:8787/mcp"))

    @override_settings(DEBUG=False)
    def test_local_mcp_host_blocked_outside_dev(self):
        self.assertFalse(is_trusted_posthog_mcp_resource("http://localhost:8787/mcp"))

    @patch(
        "posthog.api.oauth.mcp_resource_scopes.get_oauth_scopes_supported",
        return_value=["notebook:read", "notebook:write"],
    )
    @patch("posthog.api.oauth.mcp_resource_scopes.requests.get")
    def test_fetch_uses_rfc9728_metadata_path(self, mock_get: MagicMock, _mock_scopes: MagicMock):
        self._clear_mcp_scopes_cache()
        mock_get.return_value.ok = True
        mock_get.return_value.json.return_value = {
            "scopes_supported": ["notebook:read", "notebook:write"],
        }

        scopes = fetch_mcp_protected_resource_scopes("https://mcp.posthog.com/mcp")

        self.assertEqual(scopes, ["notebook:read", "notebook:write"])
        mock_get.assert_called_once_with(
            "https://mcp.posthog.com/.well-known/oauth-protected-resource/mcp",
            timeout=2,
        )

    @patch("posthog.api.oauth.mcp_resource_scopes.requests.get")
    def test_fetch_returns_none_on_invalid_json(self, mock_get: MagicMock):
        self._clear_mcp_scopes_cache()
        mock_get.return_value.ok = True
        mock_get.return_value.json.side_effect = ValueError("invalid json")

        scopes = fetch_mcp_protected_resource_scopes("https://mcp.posthog.com/mcp")

        self.assertIsNone(scopes)

    @patch(
        "posthog.api.oauth.mcp_resource_scopes.get_oauth_scopes_supported",
        return_value=["openid", "query:read"],
    )
    @patch("posthog.api.oauth.mcp_resource_scopes.requests.get")
    def test_fetch_falls_back_to_bare_well_known_on_404(self, mock_get: MagicMock, _mock_scopes: MagicMock):
        self._clear_mcp_scopes_cache()
        first = MagicMock()
        first.ok = False
        first.status_code = 404
        second = MagicMock()
        second.ok = True
        second.json.return_value = {"scopes_supported": ["openid", "query:read"]}
        mock_get.side_effect = [first, second]

        scopes = fetch_mcp_protected_resource_scopes("https://mcp.posthog.com/mcp")

        self.assertEqual(scopes, ["openid", "query:read"])
        self.assertEqual(mock_get.call_count, 2)
        mock_get.assert_any_call(
            "https://mcp.posthog.com/.well-known/oauth-protected-resource/mcp",
            timeout=2,
        )
        mock_get.assert_any_call(
            "https://mcp.posthog.com/.well-known/oauth-protected-resource",
            timeout=2,
        )

    @patch(
        "posthog.api.oauth.mcp_resource_scopes.get_oauth_scopes_supported",
        return_value=["notebook:read", "notebook:write"],
    )
    @patch("posthog.api.oauth.mcp_resource_scopes.requests.get")
    def test_fetch_uses_cache_on_second_call(self, mock_get: MagicMock, _mock_scopes: MagicMock):
        resource_url = self._MCP_RESOURCE_URL
        self._clear_mcp_scopes_cache(resource_url)
        mock_get.return_value.ok = True
        mock_get.return_value.json.return_value = {
            "scopes_supported": ["notebook:read", "notebook:write"],
        }

        first = fetch_mcp_protected_resource_scopes(resource_url)
        second = fetch_mcp_protected_resource_scopes(resource_url)

        self.assertEqual(first, ["notebook:read", "notebook:write"])
        self.assertEqual(second, ["notebook:read", "notebook:write"])
        mock_get.assert_called_once()
        self._clear_mcp_scopes_cache(resource_url)

    @patch(
        "posthog.api.oauth.mcp_resource_scopes.get_oauth_scopes_supported",
        return_value=["notebook:read", "notebook:write"],
    )
    @patch("posthog.api.oauth.mcp_resource_scopes.requests.get")
    def test_cache_key_ignores_query_and_fragment(self, mock_get: MagicMock, _mock_scopes: MagicMock):
        base_url = "https://mcp.posthog.com/mcp"
        self._clear_mcp_scopes_cache(base_url)
        mock_get.return_value.ok = True
        mock_get.return_value.json.return_value = {
            "scopes_supported": ["notebook:read", "notebook:write"],
        }

        first = fetch_mcp_protected_resource_scopes(base_url)
        second = fetch_mcp_protected_resource_scopes(f"{base_url}?cache_buster=1#frag")

        self.assertEqual(first, ["notebook:read", "notebook:write"])
        self.assertEqual(second, ["notebook:read", "notebook:write"])
        mock_get.assert_called_once()
        self._clear_mcp_scopes_cache(base_url)

    @patch("posthog.api.oauth.mcp_resource_scopes.requests.get")
    def test_fetch_caches_failures_briefly(self, mock_get: MagicMock):
        resource_url = self._MCP_RESOURCE_URL
        self._clear_mcp_scopes_cache(resource_url)
        mock_get.side_effect = requests.RequestException("connection refused")

        first = fetch_mcp_protected_resource_scopes(resource_url)
        second = fetch_mcp_protected_resource_scopes(resource_url)

        self.assertIsNone(first)
        self.assertIsNone(second)
        mock_get.assert_called_once()
        self._clear_mcp_scopes_cache(resource_url)

    @patch("posthog.api.oauth.mcp_resource_scopes.fetch_mcp_protected_resource_scopes")
    def test_build_oauth_mcp_consent_context_success(self, mock_fetch: MagicMock):
        mock_fetch.return_value = ["notebook:read", "notebook:write"]

        context = build_oauth_mcp_consent_context("https://mcp.posthog.com/mcp")

        self.assertEqual(
            context,
            {
                "is_mcp_resource": True,
                "scopes": ["notebook:read", "notebook:write"],
                "scopes_fetch_failed": False,
            },
        )

    def test_build_oauth_mcp_consent_context_ignores_untrusted_resource(self):
        self.assertIsNone(build_oauth_mcp_consent_context("https://evil.example.com/mcp"))

    @patch("posthog.api.oauth.mcp_resource_scopes.fetch_mcp_protected_resource_scopes")
    def test_build_oauth_mcp_consent_context_fetch_failure(self, mock_fetch: MagicMock):
        mock_fetch.return_value = None

        context = build_oauth_mcp_consent_context("https://mcp.posthog.com/mcp")

        self.assertEqual(
            context,
            {
                "is_mcp_resource": True,
                "scopes_fetch_failed": True,
            },
        )


@pytest.mark.skipif(
    not __import__("os").environ.get("MCP_OAUTH_LIVE_E2E"),
    reason="Set MCP_OAUTH_LIVE_E2E=1 to run live production MCP metadata e2e",
)
class TestMcpResourceScopesLive:
    def test_fetch_live_production_metadata_includes_notebook_scopes(self):
        scopes = fetch_mcp_protected_resource_scopes("https://mcp.posthog.com/mcp")

        assert scopes is not None
        assert len(scopes) >= 100
        assert "notebook:read" in scopes
        assert "notebook:write" in scopes
