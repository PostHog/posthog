from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from posthog.api.oauth.mcp_resource_scopes import (
    _tool_required_scopes,
    build_oauth_mcp_consent_context,
    is_trusted_posthog_mcp_resource,
    mcp_advertised_scopes,
)


class TestMcpResourceScopes(SimpleTestCase):
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
        # A userinfo-smuggled host must resolve to the real hostname, not the allowlisted prefix.
        self.assertFalse(is_trusted_posthog_mcp_resource("https://mcp.posthog.com@evil.com/mcp"))

    @override_settings(DEBUG=True)
    def test_is_trusted_posthog_mcp_resource_local_dev(self):
        self.assertTrue(is_trusted_posthog_mcp_resource("http://localhost:8787/mcp"))
        self.assertTrue(is_trusted_posthog_mcp_resource("http://127.0.0.1:8787/mcp"))

    @override_settings(DEBUG=False)
    def test_local_mcp_host_blocked_outside_dev(self):
        self.assertFalse(is_trusted_posthog_mcp_resource("http://localhost:8787/mcp"))

    @patch(
        "posthog.api.oauth.mcp_resource_scopes.get_oauth_scopes_supported",
        return_value=["openid", "profile", "notebook:read", "notebook:write", "webhook:write"],
    )
    @patch(
        "posthog.api.oauth.mcp_resource_scopes._tool_required_scopes",
        return_value=frozenset({"notebook:read", "notebook:write"}),
    )
    def test_advertised_scopes_keeps_identity_and_tool_required_only(self, _mock_required, _mock_supported):
        # Identity scopes (no `:`) always ride; resource scopes only if a tool needs them.
        # `webhook:write` is grantable but exercised by no tool, so it must not be advertised.
        self.assertEqual(
            mcp_advertised_scopes(),
            ["openid", "profile", "notebook:read", "notebook:write"],
        )

    def test_advertised_scopes_derives_from_real_committed_catalog(self):
        # Guards the cross-service artifact path and shape: if
        # services/mcp/schema/generated-tool-definitions.json moves or changes
        # structure, this fails loudly instead of silently advertising nothing.
        _tool_required_scopes.cache_clear()
        scopes = mcp_advertised_scopes()
        self.assertIn("openid", scopes)
        self.assertIn("notebook:read", scopes)
        self.assertGreater(len(scopes), 50)

    def test_build_oauth_mcp_consent_context_success(self):
        context = build_oauth_mcp_consent_context("https://mcp.posthog.com/mcp")

        assert context is not None
        self.assertTrue(context["is_mcp_resource"])
        self.assertIn("notebook:read", context["scopes"])

    def test_build_oauth_mcp_consent_context_ignores_untrusted_resource(self):
        self.assertIsNone(build_oauth_mcp_consent_context("https://evil.example.com/mcp"))
