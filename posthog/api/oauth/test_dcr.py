from posthog.test.base import APIBaseTest

from django.conf import settings
from django.test import override_settings

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models.oauth import OAuthApplication


def generate_rsa_key() -> str:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode("utf-8")


@override_settings(
    OAUTH2_PROVIDER={
        **settings.OAUTH2_PROVIDER,
        "OIDC_RSA_PRIVATE_KEY": generate_rsa_key(),
    }
)
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

    def test_client_secret_not_returned(self):
        """DCR should never return client_secret since we only support public clients."""
        response = self.client.post(
            "/oauth/register/",
            {
                "redirect_uris": ["https://example.com/callback"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        # Response must not contain client_secret (public clients don't use secrets)
        self.assertNotIn("client_secret", data)
        self.assertNotIn("client_secret_expires_at", data)

        # Verify the client type is public
        app = OAuthApplication.objects.get(client_id=data["client_id"])
        self.assertEqual(app.client_type, "public")

    def test_only_public_client_type_supported(self):
        """Requesting confidential client auth method should be rejected."""
        response = self.client.post(
            "/oauth/register/",
            {
                "redirect_uris": ["https://example.com/callback"],
                "token_endpoint_auth_method": "client_secret_post",
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

    def test_software_id_explicit(self):
        """Explicitly provided software_id should be stored and returned."""
        response = self.client.post(
            "/oauth/register/",
            {
                "client_name": "My Custom Client",
                "redirect_uris": ["https://example.com/callback"],
                "software_id": "my-custom-integration",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["software_id"], "my-custom-integration")

        app = OAuthApplication.objects.get(client_id=data["client_id"])
        self.assertEqual(app.software_id, "my-custom-integration")

    def test_software_id_derived_from_replit_name(self):
        """software_id should be derived from client_name containing 'replit'."""
        response = self.client.post(
            "/oauth/register/",
            {
                "client_name": "Replit MCP Client",
                "redirect_uris": ["https://example.com/callback"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["software_id"], "replit")

        app = OAuthApplication.objects.get(client_id=data["client_id"])
        self.assertEqual(app.software_id, "replit")

    def test_software_id_derived_from_claude_code_name(self):
        """software_id should be derived from client_name containing 'claude code'."""
        response = self.client.post(
            "/oauth/register/",
            {
                "client_name": "Claude Code Integration",
                "redirect_uris": ["https://example.com/callback"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["software_id"], "claude-code")

        app = OAuthApplication.objects.get(client_id=data["client_id"])
        self.assertEqual(app.software_id, "claude-code")

    def test_software_id_derived_from_cursor_name(self):
        """software_id should be derived from client_name containing 'cursor'."""
        response = self.client.post(
            "/oauth/register/",
            {
                "client_name": "Cursor Editor",
                "redirect_uris": ["https://example.com/callback"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["software_id"], "cursor")

    def test_software_id_explicit_overrides_derived(self):
        """Explicit software_id should take precedence over derived value."""
        response = self.client.post(
            "/oauth/register/",
            {
                "client_name": "Replit Custom Build",
                "redirect_uris": ["https://example.com/callback"],
                "software_id": "replit-enterprise",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["software_id"], "replit-enterprise")

        app = OAuthApplication.objects.get(client_id=data["client_id"])
        self.assertEqual(app.software_id, "replit-enterprise")

    def test_software_id_not_returned_when_unknown(self):
        """software_id should not be in response if it cannot be determined."""
        response = self.client.post(
            "/oauth/register/",
            {
                "client_name": "Unknown Client",
                "redirect_uris": ["https://example.com/callback"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertNotIn("software_id", data)

        app = OAuthApplication.objects.get(client_id=data["client_id"])
        self.assertIsNone(app.software_id)

    def test_software_id_case_insensitive_matching(self):
        """software_id derivation should be case-insensitive."""
        response = self.client.post(
            "/oauth/register/",
            {
                "client_name": "REPLIT Integration",
                "redirect_uris": ["https://example.com/callback"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["software_id"], "replit")
