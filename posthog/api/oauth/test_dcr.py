import base64
import hashlib

from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.api.oauth.client_name import sanitize_client_name
from posthog.models.oauth import OAuthApplication, OAuthApplicationAccessLevel


class TestDynamicClientRegistration(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def test_register_minimal_client(self):
        response = self.client.post(
            "/oauth/register/",
            {
                "redirect_uris": ["https://example.com/callback"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertIn("client_id", data)
        self.assertEqual(data["redirect_uris"], ["https://example.com/callback"])
        self.assertEqual(data["grant_types"], ["authorization_code"])
        self.assertEqual(data["response_types"], ["code"])
        self.assertEqual(data["token_endpoint_auth_method"], "none")
        self.assertIn("client_id_issued_at", data)

        # Verify in database
        app = OAuthApplication.objects.get(client_id=data["client_id"])
        self.assertTrue(app.is_dcr_client)
        self.assertIsNone(app.organization)
        self.assertIsNone(app.user)

    def test_register_full_client(self):
        response = self.client.post(
            "/oauth/register/",
            {
                "client_name": "Test MCP Client",
                "redirect_uris": ["https://example.com/callback", "https://example.com/callback2"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["client_name"], "Test MCP Client")
        self.assertEqual(len(data["redirect_uris"]), 2)

        # Verify name stored
        app = OAuthApplication.objects.get(client_id=data["client_id"])
        self.assertEqual(app.name, "Test MCP Client")

    def test_register_localhost_http_allowed(self):
        response = self.client.post(
            "/oauth/register/",
            {
                "redirect_uris": ["http://localhost:3000/callback"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_register_127_http_allowed(self):
        response = self.client.post(
            "/oauth/register/",
            {
                "redirect_uris": ["http://127.0.0.1:8080/callback"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_register_http_non_localhost_rejected(self):
        response = self.client.post(
            "/oauth/register/",
            {
                "redirect_uris": ["http://example.com/callback"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # Model validation returns invalid_redirect_uri
        self.assertEqual(response.json()["error"], "invalid_redirect_uri")

    def test_register_missing_redirect_uris(self):
        response = self.client.post(
            "/oauth/register/",
            {
                "client_name": "No Redirects",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_client_metadata")

    def test_register_empty_redirect_uris(self):
        response = self.client.post(
            "/oauth/register/",
            {
                "redirect_uris": [],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_invalid_grant_type(self):
        response = self.client.post(
            "/oauth/register/",
            {
                "redirect_uris": ["https://example.com/callback"],
                "grant_types": ["client_credentials"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_dcr_client_can_be_used_for_oauth(self):
        """E2E: DCR client should work with the OAuth authorization flow."""
        # Register client
        register_response = self.client.post(
            "/oauth/register/",
            {
                "client_name": "E2E Test Client",
                "redirect_uris": ["https://example.com/callback"],
            },
            format="json",
        )
        self.assertEqual(register_response.status_code, status.HTTP_201_CREATED)
        client_id = register_response.json()["client_id"]

        # Try to start OAuth flow (should not 404 or error on invalid client)
        self.client.force_login(self.user)
        auth_response = self.client.get(
            "/oauth/authorize/",
            {
                "client_id": client_id,
                "redirect_uri": "https://example.com/callback",
                "response_type": "code",
                "scope": "openid",
                "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
                "code_challenge_method": "S256",
                "state": "test123",
            },
        )
        # Should get consent page or redirect, not a client_id error
        self.assertIn(auth_response.status_code, [200, 302])

    def test_no_authentication_required(self):
        """DCR endpoint should work without any authentication."""
        # Ensure no auth headers
        self.client.logout()
        response = self.client.post(
            "/oauth/register/",
            {
                "redirect_uris": ["https://example.com/callback"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_redirect_uri_with_space_rejected(self):
        """Redirect URIs with spaces should be rejected to prevent injection attacks."""
        response = self.client.post(
            "/oauth/register/",
            {
                "redirect_uris": ["https://evil.com https://legit.com"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_client_metadata")

    def test_redirect_uri_with_whitespace_rejected(self):
        """Redirect URIs with any whitespace should be rejected."""
        response = self.client.post(
            "/oauth/register/",
            {
                "redirect_uris": ["https://example.com/callback\twith\ttabs"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_client_metadata")

    def test_public_client_no_secret_returned(self):
        response = self.client.post(
            "/oauth/register/",
            {
                "redirect_uris": ["https://example.com/callback"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertNotIn("client_secret", data)
        self.assertNotIn("client_secret_expires_at", data)

        app = OAuthApplication.objects.get(client_id=data["client_id"])
        self.assertEqual(app.client_type, "public")

    def test_confidential_client_registration(self):
        response = self.client.post(
            "/oauth/register/",
            {
                "redirect_uris": ["https://example.com/callback"],
                "token_endpoint_auth_method": "client_secret_post",
                "client_name": "Claude",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertIn("client_secret", data)
        self.assertEqual(data["client_secret_expires_at"], 0)
        self.assertEqual(data["token_endpoint_auth_method"], "client_secret_post")

        app = OAuthApplication.objects.get(client_id=data["client_id"])
        self.assertEqual(app.client_type, "confidential")
        self.assertTrue(app.is_dcr_client)

        # The returned secret must be plaintext (not a hash) and must verify against the stored hash
        from django.contrib.auth.hashers import check_password

        self.assertFalse(data["client_secret"].startswith("pbkdf2_sha256$"))
        self.assertTrue(check_password(data["client_secret"], app.client_secret))

    def test_unsupported_auth_method_rejected(self):
        response = self.client.post(
            "/oauth/register/",
            {
                "redirect_uris": ["https://example.com/callback"],
                "token_endpoint_auth_method": "client_secret_basic",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_client_metadata")

    def test_rate_limiting_enforced(self):
        """DCR endpoint should enforce rate limiting."""
        from unittest.mock import patch

        # Mock the throttle to have a very low limit
        with patch("posthog.api.oauth.dcr.DCRBurstThrottle.rate", "2/minute"):
            with patch("posthog.api.oauth.dcr.DCRBurstThrottle.get_cache_key") as mock_cache_key:
                # Use a consistent cache key for all requests
                mock_cache_key.return_value = "test_rate_limit_key"

                # First two requests should succeed
                for i in range(2):
                    response = self.client.post(
                        "/oauth/register/",
                        {"redirect_uris": [f"https://example{i}.com/callback"]},
                        format="json",
                    )
                    self.assertEqual(response.status_code, status.HTTP_201_CREATED, f"Request {i + 1} should succeed")

                # Third request should be rate limited
                response = self.client.post(
                    "/oauth/register/",
                    {"redirect_uris": ["https://example-limited.com/callback"]},
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_blocked_client_name_starts_with_posthog(self):
        """Client names starting with 'posthog' should be rejected to prevent confusion attacks."""
        response = self.client.post(
            "/oauth/register/",
            {
                "client_name": "PostHog Client",
                "redirect_uris": ["https://example.com/callback"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_client_metadata")

    def test_client_name_containing_posthog_allowed(self):
        """Client names containing 'posthog' (but not starting with it) should be allowed."""
        response = self.client.post(
            "/oauth/register/",
            {
                "client_name": "Claude Code (posthog-local)",
                "redirect_uris": ["https://example.com/callback"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_blocked_client_name_official(self):
        """Client names containing 'official' should be rejected."""
        response = self.client.post(
            "/oauth/register/",
            {
                "client_name": "Official MCP Client",
                "redirect_uris": ["https://example.com/callback"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_client_metadata")

    def test_blocked_client_name_verified(self):
        """Client names containing 'verified' should be rejected."""
        response = self.client.post(
            "/oauth/register/",
            {
                "client_name": "Verified App",
                "redirect_uris": ["https://example.com/callback"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_client_metadata")

    def test_blocked_client_name_case_insensitive(self):
        """Blocked word check should be case-insensitive."""
        response = self.client.post(
            "/oauth/register/",
            {
                "client_name": "POSTHOG Integration",
                "redirect_uris": ["https://example.com/callback"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_client_metadata")

        # Also test "official" case-insensitivity
        response = self.client.post(
            "/oauth/register/",
            {
                "client_name": "OFFICIAL App",
                "redirect_uris": ["https://example.com/callback"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_valid_client_name_accepted(self):
        """Normal client names without blocked words should be accepted."""
        response = self.client.post(
            "/oauth/register/",
            {
                "client_name": "My Analytics Dashboard",
                "redirect_uris": ["https://example.com/callback"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["client_name"], "My Analytics Dashboard")

    @parameterized.expand(
        [
            ("script_tag", "<script>alert(1)</script>"),
            ("attribute_breakout", '"><img src=x onerror=alert(1)>'),
            ("ampersand_preserved", "Acme & Co"),
            ("over_length_after_escape", "<" * 255),
        ]
    )
    def test_client_name_is_html_escaped_when_stored(self, _name, payload):
        response = self.client.post(
            "/oauth/register/",
            {"client_name": payload, "redirect_uris": ["https://example.com/callback"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Escaped once at ingestion and capped to the model's name column.
        expected = sanitize_client_name(payload)
        app = OAuthApplication.objects.get(client_id=response.json()["client_id"])
        self.assertEqual(app.name, expected)
        self.assertNotIn("<", app.name)
        self.assertNotIn(">", app.name)
        self.assertEqual(response.json()["client_name"], expected)

    @parameterized.expand(
        [
            # (name, requested scope, expected app.scopes ceiling, expected echoed `scope` in 201 — None means omitted)
            ("single_scope", "experiment:read", ["experiment:read"], "experiment:read"),
            (
                "multiple_scopes",
                "experiment:read dashboard:write",
                ["experiment:read", "dashboard:write"],
                "experiment:read dashboard:write",
            ),
            (
                "strips_privileged",
                "experiment:read llm_gateway:read llm_gateway:write",
                ["experiment:read"],
                "experiment:read",
            ),
            ("strips_internal", "experiment:read signal_scout_internal:write", ["experiment:read"], "experiment:read"),
            (
                "strips_hidden",
                "experiment:read wizard_session:write",
                ["experiment:read"],
                "experiment:read",
            ),
            ("strips_unknown_junk", "experiment:read not_a_real:scope", ["experiment:read"], "experiment:read"),
            (
                "dedupes_preserving_order",
                "experiment:read dashboard:read experiment:read",
                ["experiment:read", "dashboard:read"],
                "experiment:read dashboard:read",
            ),
            ("blank_string_yields_empty", "", [], None),
            (
                "extra_whitespace_ignored",
                "  experiment:read   dashboard:read ",
                ["experiment:read", "dashboard:read"],
                "experiment:read dashboard:read",
            ),
        ]
    )
    def test_scope_registration_writes_filtered_ceiling(self, _name, scope, expected_scopes, expected_response_scope):
        response = self.client.post(
            "/oauth/register/",
            {"redirect_uris": ["https://example.com/callback"], "scope": scope},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        app = OAuthApplication.objects.get(client_id=response.json()["client_id"])
        self.assertEqual(app.scopes, expected_scopes)
        if expected_response_scope is None:
            self.assertNotIn("scope", response.json())
        else:
            self.assertEqual(response.json()["scope"], expected_response_scope)

    @parameterized.expand(
        [
            ("only_privileged", "llm_gateway:read llm_gateway:write"),
            ("only_internal_hidden_junk", "signal_scout_internal:write wizard_session:read not_a_real:scope"),
        ]
    )
    def test_register_with_only_ungrantable_scopes_is_rejected(self, _name, scope):
        response = self.client.post(
            "/oauth/register/",
            {"redirect_uris": ["https://example.com/callback"], "scope": scope},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_client_metadata")

    def test_register_without_scope_leaves_ceiling_empty(self):
        # Distinct from blank_string above: the `scope` key is absent entirely, exercising
        # the `data.get("scope")` None branch rather than the empty-string branch.
        response = self.client.post(
            "/oauth/register/",
            {"redirect_uris": ["https://example.com/callback"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        app = OAuthApplication.objects.get(client_id=response.json()["client_id"])
        self.assertEqual(app.scopes, [])
        self.assertNotIn("scope", response.json())

    CODE_VERIFIER = "dcr_scope_test_verifier"

    @property
    def code_challenge(self) -> str:
        digest = hashlib.sha256(self.CODE_VERIFIER.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest).decode("utf-8").replace("=", "")

    def _register_dcr_client(self, **extra) -> str:
        body = {"redirect_uris": ["https://example.com/callback"], **extra}
        response = self.client.post("/oauth/register/", body, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()["client_id"]

    def _authorize_consent_post(self, client_id: str, scope: str):
        """POST the consent form, mirroring TestOAuthAPI. Returns a JSON
        `redirect_to` payload rather than rendering the consent template, so
        the assertion doesn't depend on a built frontend. The dict is passed
        directly (multipart) so empty scoped_* lists are omitted, not sent as
        the literal "[]"."""
        self.client.force_login(self.user)
        body = {
            "client_id": client_id,
            "redirect_uri": "https://example.com/callback",
            "response_type": "code",
            "code_challenge": self.code_challenge,
            "code_challenge_method": "S256",
            "allow": True,
            "access_level": OAuthApplicationAccessLevel.ALL.value,
            "scoped_organizations": [],
            "scoped_teams": [],
            "scope": scope,
        }
        return self.client.post("/oauth/authorize/", body)

    def test_no_scope_dcr_client_resolves_to_unprivileged_default_at_authorize(self):
        """Regression: a DCR client (Cursor, mcp-remote) that registers without
        scope= must resolve to the broad UNPRIVILEGED default at /authorize, so
        an unprivileged scope is granted (code issued, not invalid_scope)."""
        client_id = self._register_dcr_client()
        response = self._authorize_consent_post(client_id, "experiment:read")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        redirect_to = response.json()["redirect_to"]
        self.assertNotIn("error=invalid_scope", redirect_to)
        self.assertIn("code=", redirect_to)

    def test_no_scope_dcr_client_rejects_privileged_scope_at_authorize(self):
        """The broad default excludes PRIVILEGED_SCOPES, so a no-ceiling DCR
        client cannot obtain llm_gateway access at /authorize."""
        client_id = self._register_dcr_client()
        self.client.force_login(self.user)
        response = self.client.get(
            "/oauth/authorize/",
            {
                "client_id": client_id,
                "redirect_uri": "https://example.com/callback",
                "response_type": "code",
                "scope": "llm_gateway:read",
                "code_challenge": self.code_challenge,
                "code_challenge_method": "S256",
                "state": "test123",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        location = response.get("Location")
        assert location
        self.assertIn("error=invalid_scope", location)
