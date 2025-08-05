from unittest.mock import patch
import json
import jwt
import base64
from typing import Optional
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.utils import timezone
from rest_framework import status
from ee.models.vercel_installation import VercelInstallation
from posthog.test.base import APIBaseTest


@patch("ee.api.authentication.get_vercel_jwks")
class TestVercelInstallationAPI(APIBaseTest):
    """Test Vercel Installation API functionality (authentication/permission tests are in test_vercel_auth.py)"""

    def setUp(self):
        super().setUp()
        self.installation_id = "inst_123456789"
        self.account_id = "acc987654321"
        self.user_id = "111222333abc"

        # Create a test installation
        self.installation = VercelInstallation.objects.create(
            organization=self.organization,
            installation_id=self.installation_id,
            billing_plan_id="plan_123",
            upsert_data={"scopes": ["read", "write"], "access_token": "test_token", "token_type": "Bearer"},
        )

        # Generate test RSA key pair for JWT creation
        self.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        self.public_key = self.private_key.public_key()

        # Create JWKS with our test public key
        public_numbers = self.public_key.public_numbers()
        n = self._int_to_base64url(public_numbers.n)
        e = self._int_to_base64url(public_numbers.e)

        self.test_kid = "test_key_id"
        self.mock_jwks = {"keys": [{"kid": self.test_kid, "kty": "RSA", "use": "sig", "alg": "RS256", "n": n, "e": e}]}

    def _int_to_base64url(self, value: int) -> str:
        """Convert integer to base64url encoding without padding"""
        byte_length = (value.bit_length() + 7) // 8
        value_bytes = value.to_bytes(byte_length, byteorder="big")
        return base64.urlsafe_b64encode(value_bytes).decode("ascii").rstrip("=")

    def _create_jwt_token(self, payload: dict, headers: Optional[dict] = None) -> str:
        """Create a real JWT token for testing"""
        if headers is None:
            headers = {"kid": self.test_kid}

        private_key_pem = self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        # Convert bytes to string for PyJWT
        private_key_str = private_key_pem.decode("utf-8")

        return jwt.encode(payload, private_key_str, algorithm="RS256", headers=headers)

    def _create_user_auth_payload(
        self, installation_id: Optional[str] = None, account_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> dict:
        """Create user auth JWT payload"""
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

    def _create_system_auth_payload(
        self, installation_id: Optional[str] = None, account_id: Optional[str] = None
    ) -> dict:
        """Create system auth JWT payload"""
        account = account_id or self.account_id
        return {
            "iss": "https://marketplace.vercel.com",
            "sub": f"account:{account[3:] if account.startswith('acc') else account}",
            "aud": "test_audience",
            "account_id": account,
            "installation_id": installation_id or self.installation_id,
            "exp": timezone.now().timestamp() + 3600,
        }

    def _get_auth_headers(self, auth_type: str = "user") -> dict:
        """Create authentication headers for API requests"""
        if auth_type == "user":
            token = self._create_jwt_token(self._create_user_auth_payload())
        else:
            token = self._create_jwt_token(self._create_system_auth_payload())

        return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_VERCEL_AUTH": auth_type}

    def test_retrieve_installation(self, mock_get_jwks):
        """Test retrieving installation data"""
        mock_get_jwks.return_value = self.mock_jwks

        headers = self._get_auth_headers("user")

        response = self.client.get(f"/api/vercel/v1/installations/{self.installation_id}/", **headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["installation_id"], self.installation_id)
        self.assertEqual(data["billing_plan_id"], "plan_123")

    def test_update_installation(self, mock_get_jwks):
        """Test updating installation with valid payload"""
        mock_get_jwks.return_value = self.mock_jwks

        headers = self._get_auth_headers("user")

        update_data = {
            "scopes": ["read", "write"],
            "acceptedPolicies": {"toc": "2024-02-28T10:00:00Z"},
            "credentials": {"access_token": "new_token", "token_type": "Bearer"},
            "account": {"name": "Test Account", "url": "https://example.com", "contact": {"email": "test@example.com"}},
        }

        response = self.client.put(
            f"/api/vercel/v1/installations/{self.installation_id}/",
            data=json.dumps(update_data),
            content_type="application/json",
            **headers,
        )

        # Should pass authentication but may fail validation
        self.assertNotEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_partial_update_installation(self, mock_get_jwks):
        """Test partial update with invalid payload structure"""
        mock_get_jwks.return_value = self.mock_jwks

        headers = self._get_auth_headers("user")

        # Invalid payload - empty scopes array should fail validation
        invalid_data = {
            "scopes": [],  # Should have at least one scope
            "credentials": {"access_token": "token"},  # Missing token_type
        }

        response = self.client.patch(
            f"/api/vercel/v1/installations/{self.installation_id}/",
            data=json.dumps(invalid_data),
            content_type="application/json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_installation(self, mock_get_jwks):
        """Test deleting installation"""
        mock_get_jwks.return_value = self.mock_jwks

        headers = self._get_auth_headers("user")

        response = self.client.delete(f"/api/vercel/v1/installations/{self.installation_id}/", **headers)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(VercelInstallation.objects.filter(installation_id=self.installation_id).exists())

    def test_system_auth_retrieve_installation(self, mock_get_jwks):
        """Test retrieving installation data with system auth"""
        mock_get_jwks.return_value = self.mock_jwks

        headers = self._get_auth_headers("system")

        response = self.client.get(f"/api/vercel/v1/installations/{self.installation_id}/", **headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["installation_id"], self.installation_id)
        self.assertEqual(data["billing_plan_id"], "plan_123")
