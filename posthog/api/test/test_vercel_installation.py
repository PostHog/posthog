from unittest.mock import patch
from typing import Optional
import json
import jwt
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.utils import timezone
from rest_framework import status
from posthog.models.vercel_installation import VercelInstallation
from posthog.test.base import APIBaseTest


@patch("posthog.api.vercel_installation.get_vercel_jwks")
class TestVercelInstallationAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.installation_id = "inst_123456789"
        self.account_id = "acc987654321"  # Valid hex format
        self.user_id = "111222333abc"  # Valid hex format

        # Create a test installation
        self.installation = VercelInstallation.objects.create(
            organization=self.organization,
            installation_id=self.installation_id,
            billing_plan_id="plan_123",
            upsert_data={"scopes": ["read", "write"], "access_token": "test_token", "token_type": "Bearer"},
        )

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

    def _int_to_base64url(self, value: int) -> str:
        # Convert to bytes, ensuring proper byte length
        byte_length = (value.bit_length() + 7) // 8
        value_bytes = value.to_bytes(byte_length, byteorder="big")
        # Base64url encode without padding
        return base64.urlsafe_b64encode(value_bytes).decode("ascii").rstrip("=")

    def _create_jwt_token(self, payload: dict, headers: Optional[dict] = None) -> str:
        if headers is None:
            headers = {"kid": self.test_kid}

        # Serialize private key for PyJWT
        private_key_pem = self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

        return jwt.encode(payload, private_key_pem, algorithm="RS256", headers=headers)

    def _create_user_auth_payload(
        self, installation_id: Optional[str] = None, account_id: Optional[str] = None, user_id: Optional[str] = None
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

    def _create_system_auth_payload(
        self, installation_id: Optional[str] = None, account_id: Optional[str] = None
    ) -> dict:
        account = account_id or self.account_id
        return {
            "iss": "https://marketplace.vercel.com",
            "sub": f"account:{account[3:] if account.startswith('acc') else account}",  # Remove 'acc' prefix for sub
            "aud": "test_audience",
            "account_id": account,
            "installation_id": installation_id or self.installation_id,
            "exp": timezone.now().timestamp() + 3600,
        }

    def _get_auth_headers(self, token: str, auth_type: str) -> dict:
        return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_VERCEL_AUTH": auth_type}

    def test_user_auth_retrieve_installation(self, mock_get_jwks):
        """Test retrieving installation with valid User authentication"""
        mock_get_jwks.return_value = self.mock_jwks

        token = self._create_jwt_token(self._create_user_auth_payload())
        headers = self._get_auth_headers(token, "user")

        response = self.client.get(f"/api/vercel/v1/installations/{self.installation_id}/", **headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["installation_id"], self.installation_id)

    def test_system_auth_retrieve_installation(self, mock_get_jwks):
        """Test retrieving installation with valid System authentication"""
        mock_get_jwks.return_value = self.mock_jwks

        token = self._create_jwt_token(self._create_system_auth_payload())
        headers = self._get_auth_headers(token, "system")

        response = self.client.get(f"/api/vercel/v1/installations/{self.installation_id}/", **headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["installation_id"], self.installation_id)

    def test_user_auth_update_authentication_succeeds(self, mock_get_jwks):
        """Test that User authentication works for update endpoint (ignoring payload validation)"""
        mock_get_jwks.return_value = self.mock_jwks

        token = self._create_jwt_token(self._create_user_auth_payload())
        headers = self._get_auth_headers(token, "user")

        # Use minimal valid payload
        update_data = {
            "scopes": ["read"],
            "acceptedPolicies": {},
            "credentials": {"access_token": "token", "token_type": "Bearer"},
            "account": {"name": "", "url": "https://example.com", "contact": {"email": "test@example.com"}},
        }

        response = self.client.put(
            f"/api/vercel/v1/installations/{self.installation_id}/",
            data=json.dumps(update_data),
            content_type="application/json",
            **headers,
        )

        # Test passes auth (not 401/403) even if payload validation might fail (400)
        self.assertNotEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_system_auth_cannot_delete_installation(self, mock_get_jwks):
        """Test that System auth cannot delete installations"""
        mock_get_jwks.return_value = self.mock_jwks

        token = self._create_jwt_token(self._create_system_auth_payload())
        headers = self._get_auth_headers(token, "system")

        response = self.client.delete(f"/api/vercel/v1/installations/{self.installation_id}/", **headers)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Auth type 'System' not allowed", response.json()["detail"])

    def test_user_auth_can_delete_installation(self, mock_get_jwks):
        """Test that User auth can delete installations"""
        mock_get_jwks.return_value = self.mock_jwks

        token = self._create_jwt_token(self._create_user_auth_payload())
        headers = self._get_auth_headers(token, "user")

        response = self.client.delete(f"/api/vercel/v1/installations/{self.installation_id}/", **headers)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(VercelInstallation.objects.filter(installation_id=self.installation_id).exists())

    def test_missing_authorization_header(self, mock_get_jwks):
        """Test request without Authorization header"""
        response = self.client.get(f"/api/vercel/v1/installations/{self.installation_id}/", HTTP_X_VERCEL_AUTH="user")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_vercel_auth_header(self, mock_get_jwks):
        """Test request without X-Vercel-Auth header"""
        token = self._create_jwt_token(self._create_user_auth_payload())

        response = self.client.get(
            f"/api/vercel/v1/installations/{self.installation_id}/", HTTP_AUTHORIZATION=f"Bearer {token}"
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("Missing or invalid X-Vercel-Auth header", response.json()["detail"])

    def test_invalid_vercel_auth_header(self, mock_get_jwks):
        """Test request with invalid X-Vercel-Auth header"""
        token = self._create_jwt_token(self._create_user_auth_payload())
        headers = self._get_auth_headers(token, "invalid")

        response = self.client.get(f"/api/vercel/v1/installations/{self.installation_id}/", **headers)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("Missing or invalid X-Vercel-Auth header", response.json()["detail"])

    def test_installation_id_mismatch(self, mock_get_jwks):
        """Test that installation ID in JWT must match URL parameter"""
        mock_get_jwks.return_value = self.mock_jwks
        # JWT contains different installation_id than URL
        token = self._create_jwt_token(self._create_user_auth_payload(installation_id="different_id"))
        headers = self._get_auth_headers(token, "user")

        response = self.client.get(f"/api/vercel/v1/installations/{self.installation_id}/", **headers)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Installation ID mismatch", response.json()["detail"])

    def test_invalid_jwt_token(self, mock_get_jwks):
        """Test handling of invalid JWT token"""
        mock_get_jwks.return_value = self.mock_jwks

        token = "invalid.jwt.token"
        headers = self._get_auth_headers(token, "user")

        response = self.client.get(f"/api/vercel/v1/installations/{self.installation_id}/", **headers)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("Invalid User JWT token", response.json()["detail"])

    def test_jwks_fetch_failure(self, mock_get_jwks):
        """Test handling of JWKS fetch failure"""
        mock_get_jwks.side_effect = Exception("JWKS fetch failed")

        token = self._create_jwt_token(self._create_user_auth_payload())
        headers = self._get_auth_headers(token, "user")

        response = self.client.get(f"/api/vercel/v1/installations/{self.installation_id}/", **headers)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("User authentication failed", response.json()["detail"])

    def test_partial_update_with_invalid_payload(self, mock_get_jwks):
        """Test partial update with invalid payload structure"""
        mock_get_jwks.return_value = self.mock_jwks

        token = self._create_jwt_token(self._create_user_auth_payload())
        headers = self._get_auth_headers(token, "user")

        # Invalid payload - missing required fields
        invalid_data = {
            "scopes": [],  # Should have at least one scope
            "credentials": {
                "access_token": "token"
                # Missing token_type
            },
        }

        response = self.client.patch(
            f"/api/vercel/v1/installations/{self.installation_id}/",
            data=json.dumps(invalid_data),
            content_type="application/json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_user_role_validation(self, mock_get_jwks):
        """Test that invalid user roles are rejected"""
        mock_get_jwks.return_value = self.mock_jwks

        # Create payload with invalid user_role
        payload = self._create_user_auth_payload()
        payload["user_role"] = "INVALID_ROLE"
        token = self._create_jwt_token(payload)
        headers = self._get_auth_headers(token, "user")

        response = self.client.get(f"/api/vercel/v1/installations/{self.installation_id}/", **headers)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("Invalid user_role: INVALID_ROLE", response.json()["detail"])

    def test_system_auth_sub_format_validation(self, mock_get_jwks):
        """Test that System auth sub format is validated"""
        mock_get_jwks.return_value = self.mock_jwks

        # Create payload with invalid sub format for system auth
        payload = self._create_system_auth_payload()
        payload["sub"] = "invalid:format"
        token = self._create_jwt_token(payload)
        headers = self._get_auth_headers(token, "system")

        response = self.client.get(f"/api/vercel/v1/installations/{self.installation_id}/", **headers)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("Invalid System auth sub format: invalid:format", response.json()["detail"])

    def test_user_auth_sub_format_validation(self, mock_get_jwks):
        """Test that User auth sub format is validated"""
        mock_get_jwks.return_value = self.mock_jwks

        # Create payload with invalid sub format for user auth
        payload = self._create_user_auth_payload()
        payload["sub"] = "account:123:invalid:format"
        token = self._create_jwt_token(payload)
        headers = self._get_auth_headers(token, "user")

        response = self.client.get(f"/api/vercel/v1/installations/{self.installation_id}/", **headers)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("Invalid User auth sub format: account:123:invalid:format", response.json()["detail"])

    def test_missing_key_id_in_jwt_header(self, mock_get_jwks):
        """Test that JWT tokens without key ID are rejected"""
        mock_get_jwks.return_value = self.mock_jwks

        # Create JWT token without kid in header
        token = self._create_jwt_token(self._create_user_auth_payload(), headers={})
        headers = self._get_auth_headers(token, "user")

        response = self.client.get(f"/api/vercel/v1/installations/{self.installation_id}/", **headers)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("Token missing key ID", response.json()["detail"])

    def test_key_not_found_in_jwks(self, mock_get_jwks):
        """Test that JWT tokens with unknown key ID are rejected"""
        mock_get_jwks.return_value = self.mock_jwks

        # Create JWT token with unknown key ID
        token = self._create_jwt_token(self._create_user_auth_payload(), headers={"kid": "unknown_key_id"})
        headers = self._get_auth_headers(token, "user")

        response = self.client.get(f"/api/vercel/v1/installations/{self.installation_id}/", **headers)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("Unable to find key with ID: unknown_key_id", response.json()["detail"])

    def test_invalid_issuer_validation(self, mock_get_jwks):
        """Test that tokens with invalid issuer are rejected"""
        mock_get_jwks.return_value = self.mock_jwks

        # Create payload with invalid issuer
        payload = self._create_user_auth_payload()
        payload["iss"] = "https://invalid-issuer.com"
        token = self._create_jwt_token(payload)
        headers = self._get_auth_headers(token, "user")

        response = self.client.get(f"/api/vercel/v1/installations/{self.installation_id}/", **headers)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("Invalid issuer", response.json()["detail"])

    def test_missing_required_claims(self, mock_get_jwks):
        """Test that tokens missing required claims are rejected"""
        mock_get_jwks.return_value = self.mock_jwks

        # Create payload missing required 'iss' claim
        payload = self._create_user_auth_payload()
        del payload["iss"]
        token = self._create_jwt_token(payload)
        headers = self._get_auth_headers(token, "user")

        response = self.client.get(f"/api/vercel/v1/installations/{self.installation_id}/", **headers)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("iss", response.json()["detail"])

    def test_patch_vs_put_payload_validation(self, mock_get_jwks):
        """Test that both PATCH and PUT validate payload structure"""
        mock_get_jwks.return_value = self.mock_jwks

        token = self._create_jwt_token(self._create_user_auth_payload())
        headers = self._get_auth_headers(token, "user")

        # Invalid payload missing required fields
        invalid_data = {"scopes": []}  # Should have at least one scope

        # Test PATCH
        patch_response = self.client.patch(
            f"/api/vercel/v1/installations/{self.installation_id}/",
            data=json.dumps(invalid_data),
            content_type="application/json",
            **headers,
        )
        self.assertEqual(patch_response.status_code, status.HTTP_400_BAD_REQUEST)

        # Test PUT
        put_response = self.client.put(
            f"/api/vercel/v1/installations/{self.installation_id}/",
            data=json.dumps(invalid_data),
            content_type="application/json",
            **headers,
        )
        self.assertEqual(put_response.status_code, status.HTTP_400_BAD_REQUEST)
