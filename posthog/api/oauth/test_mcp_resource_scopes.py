import pytest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from posthog.api.oauth.mcp_resource_scopes import (
    build_oauth_mcp_consent_context,
    fetch_mcp_protected_resource_scopes,
    is_trusted_posthog_mcp_resource,
)


class TestMcpResourceScopes(SimpleTestCase):
    def test_is_trusted_posthog_mcp_resource_production(self):
        self.assertTrue(is_trusted_posthog_mcp_resource("https://mcp.posthog.com/mcp"))
        self.assertFalse(is_trusted_posthog_mcp_resource("http://mcp.posthog.com/mcp"))
        self.assertFalse(is_trusted_posthog_mcp_resource("https://evil.posthog.com/mcp"))

    @override_settings(DEBUG=True)
    def test_is_trusted_posthog_mcp_resource_local_dev(self):
        self.assertTrue(is_trusted_posthog_mcp_resource("http://localhost:8787/mcp"))
        self.assertTrue(is_trusted_posthog_mcp_resource("http://127.0.0.1:8787/mcp"))

    @override_settings(DEBUG=False)
    def test_local_mcp_host_blocked_outside_dev(self):
        self.assertFalse(is_trusted_posthog_mcp_resource("http://localhost:8787/mcp"))

    @patch("posthog.api.oauth.mcp_resource_scopes.requests.get")
    def test_fetch_uses_rfc9728_metadata_path(self, mock_get: MagicMock):
        mock_get.return_value.ok = True
        mock_get.return_value.json.return_value = {
            "scopes_supported": ["notebook:read", "notebook:write"],
        }

        scopes = fetch_mcp_protected_resource_scopes("https://mcp.posthog.com/mcp")

        self.assertEqual(scopes, ["notebook:read", "notebook:write"])
        mock_get.assert_called_once_with(
            "https://mcp.posthog.com/.well-known/oauth-protected-resource/mcp",
            timeout=5,
        )

    @patch("posthog.api.oauth.mcp_resource_scopes.requests.get")
    def test_fetch_falls_back_to_bare_well_known_on_404(self, mock_get: MagicMock):
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
            timeout=5,
        )
        mock_get.assert_any_call(
            "https://mcp.posthog.com/.well-known/oauth-protected-resource",
            timeout=5,
        )

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


@pytest.mark.network
class TestMcpResourceScopesLive:
    def test_fetch_live_production_metadata_includes_notebook_scopes(self):
        scopes = fetch_mcp_protected_resource_scopes("https://mcp.posthog.com/mcp")

        assert scopes is not None
        assert len(scopes) >= 100
        assert "notebook:read" in scopes
        assert "notebook:write" in scopes
