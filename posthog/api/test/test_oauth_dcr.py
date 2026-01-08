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
