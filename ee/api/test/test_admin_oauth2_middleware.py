import time
import base64
import hashlib
import secrets
from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.contrib.sessions.backends.db import SessionStore
from django.http import HttpResponse
from django.test import RequestFactory, override_settings

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from parameterized import parameterized

from posthog.models import User

from ee.middleware import AdminOAuth2Middleware, _get_email_from_id_token, admin_oauth2_callback


class JWTTestHelper:
    """Helper class for creating test JWT tokens."""

    def __init__(self):
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.public_key = self.private_key.public_key()
        self.test_kid = "test_key_id"

    def _int_to_base64url(self, value: int) -> str:
        byte_length = (value.bit_length() + 7) // 8
        value_bytes = value.to_bytes(byte_length, byteorder="big")
        return base64.urlsafe_b64encode(value_bytes).decode("ascii").rstrip("=")

    def get_mock_jwks(self) -> dict:
        public_numbers = self.public_key.public_numbers()
        n = self._int_to_base64url(public_numbers.n)
        e = self._int_to_base64url(public_numbers.e)
        return {"keys": [{"kid": self.test_kid, "kty": "RSA", "use": "sig", "alg": "RS256", "n": n, "e": e}]}

    def create_id_token(self, payload: dict[str, Any], kid: str | None = None) -> str:
        headers = {"kid": kid or self.test_kid}
        private_key_pem = self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return jwt.encode(payload, private_key_pem, algorithm="RS256", headers=headers)


class TestGetEmailFromIdToken(BaseTest):
    """Tests for _get_email_from_id_token function with iat and hd validation."""

    def setUp(self):
        super().setUp()
        self.jwt_helper = JWTTestHelper()
        self.base_payload = {
            "iss": "https://accounts.google.com",
            "aud": "test_client_id",
            "email": "test@posthog.com",
            "email_verified": True,
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
            "nonce": "test_nonce",
            "hd": "posthog.com",
        }

    def _get_email_with_mocked_jwks(self, token: str, allowed_domains: list[str] | None = None) -> tuple[str, dict]:
        if allowed_domains is None:
            allowed_domains = ["posthog.com"]

        with patch("jwt.PyJWKClient") as mock_client:
            mock_jwks_client = MagicMock()
            mock_signing_key = MagicMock()
            mock_signing_key.key = self.jwt_helper.public_key
            mock_jwks_client.get_signing_key_from_jwt.return_value = mock_signing_key
            mock_client.return_value = mock_jwks_client

            with override_settings(
                ADMIN_AUTH_GOOGLE_OAUTH2_KEY="test_client_id",
                ADMIN_AUTH_GOOGLE_ALLOWED_DOMAINS=allowed_domains,
            ):
                return _get_email_from_id_token(token)

    @parameterized.expand(
        [
            ("fresh_token", 0, True),
            ("one_minute_old", -60, True),
            ("just_under_5_minutes", -299, True),
            ("just_over_5_minutes", -301, False),
            ("ten_minutes_old", -600, False),
            # Future tokens are rejected by PyJWT (no clock skew allowed)
            ("1_second_future", 1, False),
            ("30_seconds_future", 30, False),
        ]
    )
    def test_iat_bounds_checking(self, name, iat_offset, expected_success):
        payload = {**self.base_payload, "iat": int(time.time()) + iat_offset}
        token = self.jwt_helper.create_id_token(payload)

        email, token_payload = self._get_email_with_mocked_jwks(token)

        if expected_success:
            self.assertEqual(email, "test@posthog.com")
            self.assertEqual(token_payload.get("email"), "test@posthog.com")
        else:
            self.assertEqual(email, "")
            self.assertEqual(token_payload, {})

    @parameterized.expand(
        [
            ("matching_single_domain", "posthog.com", ["posthog.com"], True),
            ("non_matching_domain", "other.com", ["posthog.com"], False),
            ("personal_gmail", None, ["posthog.com"], False),
            ("matching_first_of_multiple", "posthog.com", ["posthog.com", "other.com"], True),
            ("matching_second_of_multiple", "other.com", ["posthog.com", "other.com"], True),
            ("not_matching_any", "evil.com", ["posthog.com", "other.com"], False),
        ]
    )
    def test_hosted_domain_validation(self, name, hd, allowed_domains, expected_success):
        payload = {**self.base_payload}
        if hd is None:
            payload.pop("hd", None)
        else:
            payload["hd"] = hd

        token = self.jwt_helper.create_id_token(payload)
        email, token_payload = self._get_email_with_mocked_jwks(token, allowed_domains)

        if expected_success:
            self.assertEqual(email, "test@posthog.com")
        else:
            self.assertEqual(email, "")
            self.assertEqual(token_payload, {})

    def test_hd_validation_skipped_when_no_allowed_domains(self):
        """When ADMIN_AUTH_GOOGLE_ALLOWED_DOMAINS is empty, any domain should work."""
        payload = {**self.base_payload}
        payload.pop("hd", None)  # Personal Gmail

        token = self.jwt_helper.create_id_token(payload)
        email, _ = self._get_email_with_mocked_jwks(token, allowed_domains=[])

        self.assertEqual(email, "test@posthog.com")

    def test_unverified_email_rejected(self):
        payload = {**self.base_payload, "email_verified": False}
        token = self.jwt_helper.create_id_token(payload)

        email, token_payload = self._get_email_with_mocked_jwks(token)

        self.assertEqual(email, "")
        self.assertEqual(token_payload, {})

    def test_email_normalized_to_lowercase(self):
        payload = {**self.base_payload, "email": "Test@PostHog.COM"}
        token = self.jwt_helper.create_id_token(payload)

        email, _ = self._get_email_with_mocked_jwks(token)

        self.assertEqual(email, "test@posthog.com")


class TestNonceValidation(BaseTest):
    """Tests for nonce validation in admin_oauth2_callback."""

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.jwt_helper = JWTTestHelper()
        self.user = User.objects.create_and_join(
            organization=self.organization,
            email="admin@posthog.com",
            password="testpassword",
        )
        self.user.is_staff = True
        self.user.save()

    def _create_request_with_session(self, code: str, state: str) -> Any:
        request = self.factory.get(f"/admin/oauth2/callback?code={code}&state={state}")
        request.user = self.user
        request.session = SessionStore()
        return request

    def _mock_token_exchange(self, id_token: str):
        return patch("ee.middleware._exchange_code_for_token", return_value={"id_token": id_token})

    def _mock_get_email(self, email: str, payload: dict):
        return patch("ee.middleware._get_email_from_id_token", return_value=(email, payload))

    def test_valid_nonce_accepted(self):
        nonce = secrets.token_urlsafe(32)
        state = secrets.token_urlsafe(32)

        request = self._create_request_with_session("auth_code", state)
        request.session[AdminOAuth2Middleware.SESSION_STATE_KEY] = state
        request.session[AdminOAuth2Middleware.SESSION_NONCE_KEY] = nonce

        with self._mock_get_email("admin@posthog.com", {"nonce": nonce, "email": "admin@posthog.com"}):
            with self._mock_token_exchange("fake_token"):
                with override_settings(ADMIN_OAUTH2_COOKIE_SECURE=False):
                    response = admin_oauth2_callback(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/admin/")
        # Nonce should be cleared from session
        self.assertNotIn(AdminOAuth2Middleware.SESSION_NONCE_KEY, request.session)

    def test_nonce_mismatch_rejected(self):
        state = secrets.token_urlsafe(32)
        session_nonce = secrets.token_urlsafe(32)
        token_nonce = secrets.token_urlsafe(32)  # Different nonce

        request = self._create_request_with_session("auth_code", state)
        request.session[AdminOAuth2Middleware.SESSION_STATE_KEY] = state
        request.session[AdminOAuth2Middleware.SESSION_NONCE_KEY] = session_nonce

        with self._mock_get_email("admin@posthog.com", {"nonce": token_nonce, "email": "admin@posthog.com"}):
            with self._mock_token_exchange("fake_token"):
                response = admin_oauth2_callback(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/admin/")

    def test_missing_nonce_in_token_rejected(self):
        state = secrets.token_urlsafe(32)
        session_nonce = secrets.token_urlsafe(32)

        request = self._create_request_with_session("auth_code", state)
        request.session[AdminOAuth2Middleware.SESSION_STATE_KEY] = state
        request.session[AdminOAuth2Middleware.SESSION_NONCE_KEY] = session_nonce

        # Token payload without nonce
        with self._mock_get_email("admin@posthog.com", {"email": "admin@posthog.com"}):
            with self._mock_token_exchange("fake_token"):
                response = admin_oauth2_callback(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/admin/")


class TestRedirectIncludesNonce(BaseTest):
    """Tests that the OAuth redirect includes nonce parameter."""

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.user = User.objects.create_and_join(
            organization=self.organization,
            email="admin@posthog.com",
            password="testpassword",
        )
        self.user.is_staff = True
        self.user.save()

    @override_settings(
        ADMIN_AUTH_GOOGLE_OAUTH2_KEY="test_client_id",
        ADMIN_AUTH_GOOGLE_OAUTH2_SECRET="test_secret",
        ADMIN_OAUTH2_COOKIE_SECURE=False,
    )
    def test_redirect_includes_nonce_param(self):
        request = self.factory.get("/admin/")
        request.user = self.user
        request.session = SessionStore()
        request.META["HTTP_HOST"] = "localhost"

        middleware = AdminOAuth2Middleware(get_response=lambda r: HttpResponse())
        response = middleware._redirect_to_oauth2(request)

        # Check nonce is in the redirect URL
        self.assertIn("nonce=", response.url)
        # Check nonce is stored in session
        self.assertIn(AdminOAuth2Middleware.SESSION_NONCE_KEY, request.session)
        # Check the nonce in URL matches session
        session_nonce = request.session[AdminOAuth2Middleware.SESSION_NONCE_KEY]
        self.assertIn(f"nonce={session_nonce}", response.url)


class TestAllowedDomainsSettings:
    """Tests for ADMIN_AUTH_GOOGLE_ALLOWED_DOMAINS parsing."""

    @pytest.mark.parametrize(
        "env_value,expected",
        [
            ("posthog.com", ["posthog.com"]),
            ("a.com,b.com", ["a.com", "b.com"]),
            ("a.com,b.com,c.com", ["a.com", "b.com", "c.com"]),
        ],
    )
    def test_allowed_domains_parsing(self, env_value, expected):
        result = [d for d in env_value.split(",") if d]
        assert result == expected

    @pytest.mark.parametrize(
        "env_value,expected",
        [
            ("", []),
            ("a.com,,b.com", ["a.com", "b.com"]),
            (",a.com,", ["a.com"]),
            (",,", []),
        ],
    )
    def test_empty_entries_filtered(self, env_value, expected):
        result = [d for d in env_value.split(",") if d]
        assert result == expected


class TestMiddlewareVerification(BaseTest):
    """Tests for the middleware verification flow."""

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.user = User.objects.create_and_join(
            organization=self.organization,
            email="admin@posthog.com",
            password="testpassword",
        )
        self.user.is_staff = True
        self.user.save()

    @override_settings(
        ADMIN_AUTH_GOOGLE_OAUTH2_KEY="test_client_id",
        ADMIN_AUTH_GOOGLE_OAUTH2_SECRET="test_secret",
        ADMIN_OAUTH2_COOKIE_SECURE=False,
    )
    def test_valid_verification_passes(self):
        request = self.factory.get("/admin/")
        request.user = self.user
        request.session = SessionStore()

        # Set up valid verification
        verification_secret = secrets.token_urlsafe(32)
        request.session[AdminOAuth2Middleware.SESSION_VERIFICATION_SECRET_KEY] = verification_secret
        request.session[AdminOAuth2Middleware.SESSION_VERIFICATION_HASH_KEY] = AdminOAuth2Middleware._get_client_hash(
            request
        )

        secret_hash = hashlib.sha256(verification_secret.encode()).hexdigest()
        request.COOKIES[AdminOAuth2Middleware.COOKIE_NAME] = secret_hash

        middleware = AdminOAuth2Middleware(get_response=lambda r: HttpResponse("OK"))
        response = middleware(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"OK")

    @override_settings(
        ADMIN_AUTH_GOOGLE_OAUTH2_KEY="test_client_id",
        ADMIN_AUTH_GOOGLE_OAUTH2_SECRET="test_secret",
        ADMIN_OAUTH2_COOKIE_SECURE=False,
    )
    def test_cookie_mismatch_redirects_to_oauth(self):
        request = self.factory.get("/admin/")
        request.user = self.user
        request.session = SessionStore()
        request.META["HTTP_HOST"] = "localhost"

        # Set up verification with wrong cookie
        verification_secret = secrets.token_urlsafe(32)
        request.session[AdminOAuth2Middleware.SESSION_VERIFICATION_SECRET_KEY] = verification_secret
        request.session[AdminOAuth2Middleware.SESSION_VERIFICATION_HASH_KEY] = AdminOAuth2Middleware._get_client_hash(
            request
        )
        request.COOKIES[AdminOAuth2Middleware.COOKIE_NAME] = "wrong_hash"

        middleware = AdminOAuth2Middleware(get_response=lambda r: HttpResponse("OK"))
        response = middleware(request)

        # Should redirect to Google OAuth
        self.assertEqual(response.status_code, 302)
        self.assertIn("accounts.google.com", response.url)
