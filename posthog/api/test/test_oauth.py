import base64
from datetime import timedelta
import hashlib
from typing import Optional
from django.test import override_settings
from freezegun import freeze_time
from rest_framework import status
from posthog.test.base import APIBaseTest
from posthog.models.oauth import OAuthApplication, OAuthGrant
from django.utils import timezone
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from django.conf import settings
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization


def generate_rsa_key() -> str:
    # Generate a new RSA private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=4096,
    )
    # Serialize the private key to PEM format
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    rsa_key = pem.decode("utf-8")

    return rsa_key


class TestOAuthAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Create OAuth application
        self.application = OAuthApplication.objects.create(
            name="Test App",
            client_id="test_client_id",
            client_secret="test_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://localhost:8000/callback",
            user=self.user,
            hash_client_secret=True,
            algorithm="RS256",
        )

        self.code_verifier = "test_challenge"

    def get_code_challenge(self) -> str:
        """
        Given a PKCE code_verifier, return the URL-safe base64-encoded
        SHA256 digest (the code_challenge), without padding.

        This is the job of a oauth2 client library, but we use it in the tests to generate the code_challenge
        """
        digest = hashlib.sha256(self.code_verifier.encode("utf-8")).digest()
        code_challenge = base64.urlsafe_b64encode(digest).decode("utf-8").replace("=", "")
        return code_challenge

    def get_valid_authorization_url(self):
        return f"/oauth/authorize/?client_id=test_client_id&redirect_uri=http://localhost:8000/callback&response_type=code&code_challenge={self.get_code_challenge()}&code_challenge_method=S256"

    def replace_param_in_url(self, url: str, param: str, value: Optional[str] = None) -> str:
        """
        Return `url` with the query parameter `param` replaced by `value`.
        If `value` is None, the parameter is removed entirely.
        """
        parts = urlparse(url)
        qs = parse_qs(parts.query, keep_blank_values=True)

        if value is None:
            qs.pop(param, None)
        else:
            qs[param] = [value]

        new_query = urlencode(qs, doseq=True)
        return urlunparse(parts._replace(query=new_query))

    def test_authorize_successful_with_required_params(self):
        response = self.client.get(self.get_valid_authorization_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_authorize_missing_client_id(self):
        url = self.get_valid_authorization_url()

        url_without_client_id = self.replace_param_in_url(url, "client_id", None)

        response = self.client.get(url_without_client_id)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_request")
        self.assertEqual(response.json()["error_description"], "Missing client_id parameter.")

    def test_authorize_invalid_client_id(self):
        url = self.get_valid_authorization_url()

        url_without_client_id = self.replace_param_in_url(url, "client_id", "invalid_id")

        response = self.client.get(url_without_client_id)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_request")
        self.assertEqual(response.json()["error_description"], "Invalid client_id parameter value.")

    def test_authorize_missing_redirect_uri(self):
        # According to the spec, if the client has a single redirect URI, the authorization server does not require an
        # explicit redirect_uri parameter and can use the one provided by the application.
        url = self.get_valid_authorization_url()

        url_without_redirect_uri = self.replace_param_in_url(url, "redirect_uri", None)

        response = self.client.get(url_without_redirect_uri)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_authorize_rejects_if_missing_redirect_uri_and_multiple_redirect_uris(self):
        # According to the spec, if the client has multiple redirect URIs, the authorization server MUST require an
        # explicit redirect_uri parameter.
        url = self.get_valid_authorization_url()
        self.application.redirect_uris = "http://localhost:8000/callback http://localhost:8001/callback"
        self.application.save()

        url_without_redirect_uri = self.replace_param_in_url(url, "redirect_uri", None)

        response = self.client.get(url_without_redirect_uri)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_request")
        self.assertEqual(response.json()["error_description"], "Missing redirect URI.")

    def test_authorize_invalid_redirect_uri(self):
        url = self.get_valid_authorization_url()

        url_without_redirect_uri = self.replace_param_in_url(url, "redirect_uri", "http://invalid.com/callback")

        response = self.client.get(url_without_redirect_uri)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_request")
        self.assertEqual(response.json()["error_description"], "Mismatching redirect URI.")

    def test_authorize_fails_without_pkce(self):
        url = self.get_valid_authorization_url()

        url_without_code_challenge = self.replace_param_in_url(url, "code_challenge", None)

        response = self.client.get(url_without_code_challenge)

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

        location = response["Location"]

        self.assertIn("error=invalid_request", location)
        self.assertIn("error_description=Code+challenge+required", location)

    @freeze_time("2025-01-01 00:00:00")
    def test_authorize_post_authorization_granted(self):
        response = self.client.post(
            "/oauth/authorize/",
            {
                "client_id": "test_client_id",
                "redirect_uri": "http://localhost:8000/callback",
                "response_type": "code",
                "code_challenge": self.get_code_challenge(),
                "code_challenge_method": "S256",
                "allow": True,
            },
        )
        redirect_to = response.json()["redirect_to"]
        self.assertIn("code=", redirect_to)

        code = redirect_to.split("code=")[1].split("&")[0]

        grant = OAuthGrant.objects.get(code=code)

        self.assertEqual(grant.application, self.application)
        self.assertEqual(grant.user, self.user)
        self.assertEqual(grant.code, code)
        self.assertEqual(grant.code_challenge, self.get_code_challenge())
        self.assertEqual(grant.code_challenge_method, "S256")

        expiration_minutes = settings.OAUTH2_PROVIDER["AUTHORIZATION_CODE_EXPIRE_SECONDS"] / 60
        expected_expiration = timezone.now() + timedelta(minutes=expiration_minutes)
        self.assertEqual(grant.expires, expected_expiration)

    def test_authorize_post_denied_authorization(self):
        response = self.client.post(
            "/oauth/authorize/",
            {
                "client_id": "test_client_id",
                "redirect_uri": "http://localhost:8000/callback",
                "response_type": "code",
                "code_challenge": self.get_code_challenge(),
                "code_challenge_method": "S256",
                "allow": False,
            },
        )
        redirect_to = response.json()["redirect_to"]
        self.assertEqual(redirect_to, "http://localhost:8000/callback?error=access_denied")

    def test_cannot_get_token_with_invalid_code(self):
        data = {
            "grant_type": "authorization_code",
            "code": "invalid_code",
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
            "redirect_uri": "http://localhost:8000/callback",
            "code_verifier": self.code_verifier,
        }

        body = urlencode(data)

        response = self.client.post("/oauth/token/", body, content_type="application/x-www-form-urlencoded")

        # Assert the response
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_grant")

    @freeze_time("2025-01-01 00:00:00")
    def test_cannot_get_token_with_expired_code(self):
        expired_grant = OAuthGrant.objects.create(
            application=self.application,
            user=self.user,
            code="expired_code",
            code_challenge=self.get_code_challenge(),
            code_challenge_method="S256",
            expires=timezone.now() - timedelta(minutes=1),
        )

        data = {
            "grant_type": "authorization_code",
            "code": expired_grant.code,
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
            "redirect_uri": "http://localhost:8000/callback",
            "code_verifier": self.code_verifier,
        }

        body = urlencode(data)

        response = self.client.post("/oauth/token/", body, content_type="application/x-www-form-urlencoded")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_grant")

    def test_token_endpoint_missing_grant_type(self):
        response = self.client.post(
            "/oauth/token/", body=urlencode({}), content_type="application/x-www-form-urlencoded"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "unsupported_grant_type")

    def test_token_endpoint_invalid_grant(self):
        data = {
            "grant_type": "authorization_code",
            "code": "invalid_code",
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
            "redirect_uri": "http://localhost:8000/callback",
            "code_verifier": self.code_verifier,
        }

        body = urlencode(data)

        response = self.client.post("/oauth/token/", body, content_type="application/x-www-form-urlencoded")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_grant")

    @override_settings(
        OAUTH2_PROVIDER={
            **settings.OAUTH2_PROVIDER,
            "OIDC_RSA_PRIVATE_KEY": generate_rsa_key(),
        }
    )
    def test_full_oauth_flow(self):
        # 1. Get authorization request
        response = self.client.get(self.get_valid_authorization_url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # 2. Post authorization approval
        response = self.client.post(
            "/oauth/authorize/",
            {
                "client_id": "test_client_id",
                "redirect_uri": "http://localhost:8000/callback",
                "response_type": "code",
                "code_challenge": self.get_code_challenge(),
                "code_challenge_method": "S256",
                "allow": True,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Extract authorization code from redirect URL
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
            "redirect_uri": "http://localhost:8000/callback",
            "code_verifier": self.code_verifier,
        }

        body = urlencode(data)

        response = self.client.post("/oauth/token/", body, content_type="application/x-www-form-urlencoded")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertIn("access_token", data)
        self.assertIn("token_type", data)
        self.assertIn("expires_in", data)
        self.assertIn("refresh_token", data)
        self.assertIn("scope", data)

    @freeze_time("2025-01-01 00:00:00")
    def test_token_endpoint_invalid_client_credentials(self):
        grant = OAuthGrant.objects.create(
            application=self.application,
            user=self.user,
            code="test_code",
            code_challenge=self.get_code_challenge(),
            code_challenge_method="S256",
            expires=timezone.now() + timedelta(minutes=1),
        )

        data = {
            "grant_type": "client_credentials",
            "client_id": "test_client_id",
            "client_secret": "wrong_secret",
            "redirect_uri": "http://localhost:8000/callback",
            "code_verifier": self.code_verifier,
            "code": grant.code,
        }

        body = urlencode(data)

        response = self.client.post("/oauth/token/", body, content_type="application/x-www-form-urlencoded")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @override_settings(
        OAUTH2_PROVIDER={
            **settings.OAUTH2_PROVIDER,
            "OIDC_RSA_PRIVATE_KEY": generate_rsa_key(),
        }
    )
    @freeze_time("2025-01-01 00:00:00")
    def test_refresh_token_flow(self):
        application = OAuthApplication.objects.create(
            name="Test Refresh App",
            client_id="test_refresh_client_id",
            client_secret="test_refresh_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://localhost:8000/callback",
            user=self.user,
            hash_client_secret=True,
            algorithm="RS256",
        )

        # First get a token
        grant = OAuthGrant.objects.create(
            application=application,
            user=self.user,
            code="test_code",
            code_challenge=self.get_code_challenge(),
            code_challenge_method="S256",
            expires=timezone.now() + timedelta(minutes=1),
        )

        data = {
            "grant_type": "authorization_code",
            "client_id": "test_refresh_client_id",
            "client_secret": "test_refresh_client_secret",
            "redirect_uri": "http://localhost:8000/callback",
            "code_verifier": self.code_verifier,
            "code": grant.code,
        }

        body = urlencode(data)

        response = self.client.post("/oauth/token/", body, content_type="application/x-www-form-urlencoded")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        refresh_token = response.json()["refresh_token"]

        self.assertNotEqual(refresh_token, None)

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        body = urlencode(data)

        response = self.client.post("/oauth/token/", body, content_type="application/x-www-form-urlencoded")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("access_token", data)
        self.assertIn("refresh_token", data)
