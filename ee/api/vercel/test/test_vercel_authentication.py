import json
import base64
from datetime import UTC, datetime
from typing import Any

from posthog.test.base import SimpleTestCase
from unittest.mock import patch

from django.utils import timezone

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIRequestFactory

from ee.api.authentication import VercelAuthentication
from ee.api.vercel.types import VercelUser


@patch("ee.api.authentication.get_vercel_jwks")
@patch("ee.settings.VERCEL_CLIENT_INTEGRATION_ID", "test_audience")
class TestVercelAuthentication(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.installation_id = "icfg_9bceb8ccT32d3U417ezb5c8p"
        self.account_id = "acc987654321"
        self.user_id = "111222333abc"

        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.public_key = self.private_key.public_key()

        public_numbers = self.public_key.public_numbers()
        n = self._int_to_base64url(public_numbers.n)
        e = self._int_to_base64url(public_numbers.e)

        self.test_kid = "test_key_id"
        self.mock_jwks = {"keys": [{"kid": self.test_kid, "kty": "RSA", "use": "sig", "alg": "RS256", "n": n, "e": e}]}

        self.factory = APIRequestFactory()
        self.auth = VercelAuthentication()

    def _int_to_base64url(self, value: int) -> str:
        byte_length = (value.bit_length() + 7) // 8
        value_bytes = value.to_bytes(byte_length, byteorder="big")
        return base64.urlsafe_b64encode(value_bytes).decode("ascii").rstrip("=")

    def _create_jwt_token(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> str:
        if headers is None:
            headers = {"kid": self.test_kid}

        private_key_pem = self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        private_key_str = private_key_pem.decode("utf-8")
        return jwt.encode(payload, private_key_str, algorithm="RS256", headers=headers)

    def _create_user_auth_payload(
        self, installation_id: str | None = None, account_id: str | None = None, user_id: str | None = None
    ) -> dict[str, Any]:
        return {
            "iss": "https://marketplace.vercel.com",
            "sub": f"account:{account_id or self.account_id}:user:{user_id or self.user_id}",
            "aud": "test_audience",
            "account_id": account_id or self.account_id,
            "installation_id": installation_id or self.installation_id,
            "user_id": user_id or self.user_id,
            "user_role": "ADMIN",
            "exp": self._exp(),
        }

    def _create_system_auth_payload(
        self, installation_id: str | None = None, account_id: str | None = None
    ) -> dict[str, Any]:
        account = account_id or self.account_id
        clean_account = account[3:] if account.startswith("acc") else account
        return {
            "iss": "https://marketplace.vercel.com",
            "sub": f"account:{clean_account}",
            "aud": "test_audience",
            "account_id": account,
            "installation_id": installation_id or self.installation_id,
            "exp": self._exp(),
        }

    def _make_request(self, token: str, auth_type: str = "user"):
        return self.factory.get("/", HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_VERCEL_AUTH=auth_type)

    def _token(self, user: bool = True, overrides: dict[str, Any] | None = None) -> str:
        payload = self._create_user_auth_payload() if user else self._create_system_auth_payload()
        if overrides:
            payload.update(overrides)
        return self._create_jwt_token(payload)

    def _assert_auth_fail(self, token: str, auth_type: str, msg: str):
        request = self._make_request(token, auth_type)
        with self.assertRaises(AuthenticationFailed) as cm:
            self.auth.authenticate(request)
        assert msg in str(cm.exception)

    def _exp(self, seconds: int = 3600) -> float:
        return timezone.now().timestamp() + seconds

    def test_user_auth_valid_token(self, mock_get_jwks):
        mock_get_jwks.return_value = self.mock_jwks
        token = self._token()
        request = self._make_request(token)

        result = self.auth.authenticate(request)

        assert result is not None
        user, auth_data = result
        assert isinstance(user, VercelUser)
        assert user.claims.account_id == self.account_id
        assert user.claims.installation_id == self.installation_id

    def test_system_auth_valid_token(self, mock_get_jwks):
        mock_get_jwks.return_value = self.mock_jwks
        token = self._token(user=False)
        request = self._make_request(token, "system")

        result = self.auth.authenticate(request)

        assert result is not None
        user, auth_data = result
        assert isinstance(user, VercelUser)
        assert user.claims.account_id == self.account_id
        assert user.claims.installation_id == self.installation_id

    def test_missing_authorization_header(self, mock_get_jwks):
        request = self.factory.get("/", HTTP_X_VERCEL_AUTH="user")
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(request)

    def test_missing_vercel_auth_header(self, mock_get_jwks):
        token = self._token()
        request = self.factory.get("/", HTTP_AUTHORIZATION=f"Bearer {token}")
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(request)

    def test_invalid_vercel_auth_header(self, mock_get_jwks):
        token = self._token()
        self._assert_auth_fail(token, "invalid", "Missing or invalid X-Vercel-Auth header")

    def test_invalid_jwt_token(self, mock_get_jwks):
        mock_get_jwks.return_value = self.mock_jwks
        self._assert_auth_fail("invalid.jwt.token", "user", "Invalid user authentication token")

    def test_missing_key_id_in_jwt_header(self, mock_get_jwks):
        mock_get_jwks.return_value = self.mock_jwks
        token = self._create_jwt_token(self._create_user_auth_payload(), headers={})
        self._assert_auth_fail(token, "user", "Invalid user authentication token")

    def test_key_not_found_in_jwks(self, mock_get_jwks):
        mock_get_jwks.return_value = self.mock_jwks
        token = self._create_jwt_token(self._create_user_auth_payload(), headers={"kid": "unknown_key_id"})
        self._assert_auth_fail(token, "user", "Invalid user authentication token")

    def test_invalid_issuer_validation(self, mock_get_jwks):
        mock_get_jwks.return_value = self.mock_jwks
        token = self._token(overrides={"iss": "https://invalid-issuer.com"})
        self._assert_auth_fail(token, "user", "Invalid user authentication token")

    def test_missing_required_claims(self, mock_get_jwks):
        mock_get_jwks.return_value = self.mock_jwks
        payload = self._create_user_auth_payload()
        del payload["iss"]
        token = self._create_jwt_token(payload)
        self._assert_auth_fail(token, "user", "Invalid user authentication token")

    def test_user_role_validation(self, mock_get_jwks):
        mock_get_jwks.return_value = self.mock_jwks
        token = self._token(overrides={"user_role": "INVALID_ROLE"})
        self._assert_auth_fail(token, "user", "Invalid user authentication token")

    def test_system_auth_sub_format_validation(self, mock_get_jwks):
        mock_get_jwks.return_value = self.mock_jwks
        token = self._token(user=False, overrides={"sub": "invalid:format"})
        self._assert_auth_fail(token, "system", "Invalid system authentication token")

    def test_user_auth_sub_format_validation(self, mock_get_jwks):
        mock_get_jwks.return_value = self.mock_jwks
        token = self._token(overrides={"sub": "account:123:invalid:format"})
        self._assert_auth_fail(token, "user", "Invalid user authentication token")

    @patch("django.utils.timezone.now")
    def test_expired_token_validation(self, mock_now, mock_get_jwks):
        mock_get_jwks.return_value = self.mock_jwks
        fixed_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        mock_now.return_value = fixed_time

        expired_timestamp = fixed_time.timestamp() - 3600
        token = self._token(overrides={"exp": expired_timestamp})
        self._assert_auth_fail(token, "user", "Invalid user authentication token")

    def test_jwks_fetch_failure(self, mock_get_jwks):
        mock_get_jwks.side_effect = Exception("JWKS fetch failed")
        token = self._token()
        request = self._make_request(token)
        with self.assertRaises(AuthenticationFailed) as cm:
            self.auth.authenticate(request)
        assert "User authentication failed" in str(cm.exception)

    def test_jwks_cache_behavior(self, mock_get_jwks):
        mock_get_jwks.return_value = self.mock_jwks
        token = self._token()

        result1 = self.auth.authenticate(self._make_request(token))
        result2 = self.auth.authenticate(self._make_request(token))

        assert result1 is not None
        assert result2 is not None
        assert mock_get_jwks.call_count >= 1

    def test_none_algorithm_rejected(self, mock_get_jwks):
        mock_get_jwks.return_value = self.mock_jwks
        # Create a token with "none" algorithm
        payload = self._create_user_auth_payload()
        # Manually create a JWT with "none" algorithm
        header = {"alg": "none", "typ": "JWT"}
        header_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=").decode()
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        none_token = f"{header_b64}.{payload_b64}."

        self._assert_auth_fail(none_token, "user", "Invalid user authentication token")
