from unittest.mock import patch
import jwt
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.utils import timezone
from rest_framework.test import APIRequestFactory
from posthog.test.base import SimpleTestCase


@patch("ee.api.authentication.get_vercel_jwks")
@patch("ee.settings.VERCEL_CLIENT_INTEGRATION_ID", "test_audience")
class TestVercelAuthentication(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.installation_id = "inst_123456789"
        self.account_id = "acc987654321"  # Valid hex format
        self.user_id = "111222333abc"  # Valid hex format

        # Generate test RSA key pair
        self.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        self.public_key = self.private_key.public_key()

        # Create JWKS with our test public key
        public_numbers = self.public_key.public_numbers()
        # Convert to base64url without padding
        n = self._int_to_base64url(public_numbers.n)
        e = self._int_to_base64url(public_numbers.e)

        self.test_kid = "test_key_id"
        self.mock_jwks = {"keys": [{"kid": self.test_kid, "kty": "RSA", "use": "sig", "alg": "RS256", "n": n, "e": e}]}

        # Create request factory for creating mock requests
        self.factory = APIRequestFactory()

    def _int_to_base64url(self, value: int) -> str:
        # Convert to bytes, ensuring proper byte length
        byte_length = (value.bit_length() + 7) // 8
        value_bytes = value.to_bytes(byte_length, byteorder="big")
        # Base64url encode without padding
        return base64.urlsafe_b64encode(value_bytes).decode("ascii").rstrip("=")

    def _create_jwt_token(self, payload: dict, headers: dict | None = None) -> str:
        if headers is None:
            headers = {"kid": self.test_kid}

        # Serialize private key for PyJWT
        private_key_pem = self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        # Convert bytes to string for PyJWT
        private_key_str = private_key_pem.decode("utf-8")

        return jwt.encode(payload, private_key_str, algorithm="RS256", headers=headers)

    def _create_user_auth_payload(
        self, installation_id: str | None = None, account_id: str | None = None, user_id: str | None = None
    ) -> dict:
        return {
            "iss": "https://marketplace.vercel.com",
            "sub": f"account:{account_id or self.account_id}:user:{user_id or self.user_id}",
            "aud": "test_audience",
            "account_id": account_id or self.account_id,
            "installation_id": installation_id or self.installation_id,
            "user_id": user_id or self.user_id,
            "user_role": "ADMIN",
            "exp": timezone.now().timestamp() + 3600,
        }

    def _create_system_auth_payload(self, installation_id: str | None = None, account_id: str | None = None) -> dict:
        account = account_id or self.account_id
        # Ensure consistent format handling for account_id in sub
        clean_account = account[3:] if account.startswith("acc") else account
        return {
            "iss": "https://marketplace.vercel.com",
            "sub": f"account:{clean_account}",
            "aud": "test_audience",
            "account_id": account,
            "installation_id": installation_id or self.installation_id,
            "exp": timezone.now().timestamp() + 3600,
        }

    def test_user_auth_valid_token(self, mock_get_jwks):
        """Test valid User authentication with real JWT"""
        mock_get_jwks.return_value = self.mock_jwks

        from ee.api.authentication import VercelAuthentication

        auth = VercelAuthentication()
        token = self._create_jwt_token(self._create_user_auth_payload())

        # Create mock request using APIRequestFactory
        request = self.factory.get("/", HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_VERCEL_AUTH="user")
        request.auth = None

        result = auth.authenticate(request)

        self.assertIsNotNone(result)
        user, payload = result
        self.assertEqual(payload["account_id"], self.account_id)
        self.assertEqual(payload["installation_id"], self.installation_id)

    def test_system_auth_valid_token(self, mock_get_jwks):
        """Test valid System authentication with real JWT"""
        mock_get_jwks.return_value = self.mock_jwks

        from ee.api.authentication import VercelAuthentication

        auth = VercelAuthentication()
        token = self._create_jwt_token(self._create_system_auth_payload())

        # Create mock request using APIRequestFactory
        request = self.factory.get("/", HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_VERCEL_AUTH="system")
        request.auth = None

        result = auth.authenticate(request)

        self.assertIsNotNone(result)
        user, payload = result
        self.assertEqual(payload["account_id"], self.account_id)
        self.assertEqual(payload["installation_id"], self.installation_id)

    def test_missing_authorization_header(self, mock_get_jwks):
        """Test authentication with missing Authorization header"""
        from ee.api.authentication import VercelAuthentication

        auth = VercelAuthentication()

        # Create mock request without Authorization header using APIRequestFactory
        request = self.factory.get("/", HTTP_X_VERCEL_AUTH="user")
        request.auth = None

        result = auth.authenticate(request)

        self.assertIsNone(result)

    def test_missing_vercel_auth_header(self, mock_get_jwks):
        """Test authentication with missing X-Vercel-Auth header"""
        from ee.api.authentication import VercelAuthentication
        from rest_framework.exceptions import AuthenticationFailed

        auth = VercelAuthentication()
        token = self._create_jwt_token(self._create_user_auth_payload())

        # Create mock request without X-Vercel-Auth header using APIRequestFactory
        request = self.factory.get("/", HTTP_AUTHORIZATION=f"Bearer {token}")
        request.auth = None

        with self.assertRaises(AuthenticationFailed) as cm:
            auth.authenticate(request)

        self.assertIn("Missing or invalid X-Vercel-Auth header", str(cm.exception))

    def test_invalid_vercel_auth_header(self, mock_get_jwks):
        """Test authentication with invalid X-Vercel-Auth header"""
        from ee.api.authentication import VercelAuthentication
        from rest_framework.exceptions import AuthenticationFailed

        auth = VercelAuthentication()
        token = self._create_jwt_token(self._create_user_auth_payload())

        # Create mock request with invalid X-Vercel-Auth header using APIRequestFactory
        request = self.factory.get("/", HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_VERCEL_AUTH="invalid")
        request.auth = None

        with self.assertRaises(AuthenticationFailed) as cm:
            auth.authenticate(request)

        self.assertIn("Missing or invalid X-Vercel-Auth header", str(cm.exception))

    def test_invalid_jwt_token(self, mock_get_jwks):
        """Test authentication with invalid JWT token"""
        mock_get_jwks.return_value = self.mock_jwks

        from ee.api.authentication import VercelAuthentication
        from rest_framework.exceptions import AuthenticationFailed

        auth = VercelAuthentication()

        # Create mock request with invalid JWT using APIRequestFactory
        request = self.factory.get("/", HTTP_AUTHORIZATION="Bearer invalid.jwt.token", HTTP_X_VERCEL_AUTH="user")
        request.auth = None

        with self.assertRaises(AuthenticationFailed) as cm:
            auth.authenticate(request)

        self.assertIn("JWT token", str(cm.exception))

    def test_missing_key_id_in_jwt_header(self, mock_get_jwks):
        """Test authentication with JWT token missing key ID"""
        mock_get_jwks.return_value = self.mock_jwks

        from ee.api.authentication import VercelAuthentication
        from rest_framework.exceptions import AuthenticationFailed

        auth = VercelAuthentication()
        token = self._create_jwt_token(self._create_user_auth_payload(), headers={})

        # Create mock request using APIRequestFactory
        request = self.factory.get("/", HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_VERCEL_AUTH="user")
        request.auth = None

        with self.assertRaises(AuthenticationFailed) as cm:
            auth.authenticate(request)

        self.assertIn("Token missing key ID", str(cm.exception))

    def test_key_not_found_in_jwks(self, mock_get_jwks):
        """Test authentication with unknown key ID"""
        mock_get_jwks.return_value = self.mock_jwks

        from ee.api.authentication import VercelAuthentication
        from rest_framework.exceptions import AuthenticationFailed

        auth = VercelAuthentication()
        token = self._create_jwt_token(self._create_user_auth_payload(), headers={"kid": "unknown_key_id"})

        # Create mock request using APIRequestFactory
        request = self.factory.get("/", HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_VERCEL_AUTH="user")
        request.auth = None

        with self.assertRaises(AuthenticationFailed) as cm:
            auth.authenticate(request)

        self.assertIn("Unable to find key with ID: unknown_key_id", str(cm.exception))

    def test_invalid_issuer_validation(self, mock_get_jwks):
        """Test authentication with invalid issuer"""
        mock_get_jwks.return_value = self.mock_jwks

        from ee.api.authentication import VercelAuthentication
        from rest_framework.exceptions import AuthenticationFailed

        auth = VercelAuthentication()

        # Create payload with invalid issuer
        payload = self._create_user_auth_payload()
        payload["iss"] = "https://invalid-issuer.com"
        token = self._create_jwt_token(payload)

        # Create mock request using APIRequestFactory
        request = self.factory.get("/", HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_VERCEL_AUTH="user")
        request.auth = None

        with self.assertRaises(AuthenticationFailed) as cm:
            auth.authenticate(request)

        self.assertIn("Invalid issuer", str(cm.exception))

    def test_missing_required_claims(self, mock_get_jwks):
        """Test authentication with missing required claims"""
        mock_get_jwks.return_value = self.mock_jwks

        from ee.api.authentication import VercelAuthentication
        from rest_framework.exceptions import AuthenticationFailed

        auth = VercelAuthentication()

        # Create payload missing required 'iss' claim
        payload = self._create_user_auth_payload()
        del payload["iss"]
        token = self._create_jwt_token(payload)

        # Create mock request using APIRequestFactory
        request = self.factory.get("/", HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_VERCEL_AUTH="user")
        request.auth = None

        with self.assertRaises(AuthenticationFailed) as cm:
            auth.authenticate(request)

        self.assertIn("iss", str(cm.exception))

    def test_user_role_validation(self, mock_get_jwks):
        """Test authentication with invalid user role"""
        mock_get_jwks.return_value = self.mock_jwks

        from ee.api.authentication import VercelAuthentication
        from rest_framework.exceptions import AuthenticationFailed

        auth = VercelAuthentication()

        # Create payload with invalid user_role
        payload = self._create_user_auth_payload()
        payload["user_role"] = "INVALID_ROLE"
        token = self._create_jwt_token(payload)

        # Create mock request using APIRequestFactory
        request = self.factory.get("/", HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_VERCEL_AUTH="user")
        request.auth = None

        with self.assertRaises(AuthenticationFailed) as cm:
            auth.authenticate(request)

        self.assertIn("Invalid user_role: INVALID_ROLE", str(cm.exception))

    def test_system_auth_sub_format_validation(self, mock_get_jwks):
        """Test System auth sub format validation"""
        mock_get_jwks.return_value = self.mock_jwks

        from ee.api.authentication import VercelAuthentication
        from rest_framework.exceptions import AuthenticationFailed

        auth = VercelAuthentication()

        # Create payload with invalid sub format for system auth
        payload = self._create_system_auth_payload()
        payload["sub"] = "invalid:format"
        token = self._create_jwt_token(payload)

        # Create mock request using APIRequestFactory
        request = self.factory.get("/", HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_VERCEL_AUTH="system")
        request.auth = None

        with self.assertRaises(AuthenticationFailed) as cm:
            auth.authenticate(request)

        self.assertIn("Invalid System auth sub format: invalid:format", str(cm.exception))

    def test_user_auth_sub_format_validation(self, mock_get_jwks):
        """Test User auth sub format validation"""
        mock_get_jwks.return_value = self.mock_jwks

        from ee.api.authentication import VercelAuthentication
        from rest_framework.exceptions import AuthenticationFailed

        auth = VercelAuthentication()

        # Create payload with invalid sub format for user auth
        payload = self._create_user_auth_payload()
        payload["sub"] = "account:123:invalid:format"
        token = self._create_jwt_token(payload)

        # Create mock request using APIRequestFactory
        request = self.factory.get("/", HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_VERCEL_AUTH="user")
        request.auth = None

        with self.assertRaises(AuthenticationFailed) as cm:
            auth.authenticate(request)

        self.assertIn("Invalid User auth sub format: account:123:invalid:format", str(cm.exception))

    def test_expired_token_validation(self, mock_get_jwks):
        """Test authentication with expired JWT token"""
        mock_get_jwks.return_value = self.mock_jwks

        from ee.api.authentication import VercelAuthentication
        from rest_framework.exceptions import AuthenticationFailed

        auth = VercelAuthentication()

        # Create payload with expired timestamp (1 hour ago)
        payload = self._create_user_auth_payload()
        payload["exp"] = timezone.now().timestamp() - 3600  # 1 hour ago
        token = self._create_jwt_token(payload)

        # Create mock request using APIRequestFactory
        request = self.factory.get("/", HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_VERCEL_AUTH="user")
        request.auth = None

        with self.assertRaises(AuthenticationFailed) as cm:
            auth.authenticate(request)

        self.assertIn("Signature has expired", str(cm.exception))

    def test_jwks_fetch_failure(self, mock_get_jwks):
        """Test authentication when JWKS fetch fails"""
        mock_get_jwks.side_effect = Exception("JWKS fetch failed")

        from ee.api.authentication import VercelAuthentication

        auth = VercelAuthentication()
        token = self._create_jwt_token(self._create_user_auth_payload())

        # Create mock request using APIRequestFactory
        request = self.factory.get("/", HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_VERCEL_AUTH="user")
        request.auth = None

        # The exception should be raised directly since we're not catching it
        with self.assertRaises(Exception) as cm:
            auth.authenticate(request)

        self.assertIn("JWKS fetch failed", str(cm.exception))

    def test_jwks_cache_behavior(self, mock_get_jwks):
        """Test that JWKS function is called and authentication works"""
        mock_get_jwks.return_value = self.mock_jwks

        from ee.api.authentication import VercelAuthentication

        auth = VercelAuthentication()
        token = self._create_jwt_token(self._create_user_auth_payload())

        # Create multiple requests
        request1 = self.factory.get("/", HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_VERCEL_AUTH="user")
        request1.auth = None

        request2 = self.factory.get("/", HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_VERCEL_AUTH="user")
        request2.auth = None

        # Both authentications should work
        result1 = auth.authenticate(request1)
        self.assertIsNotNone(result1)

        result2 = auth.authenticate(request2)
        self.assertIsNotNone(result2)

        # Verify get_vercel_jwks was called at least once
        self.assertGreater(mock_get_jwks.call_count, 0)
