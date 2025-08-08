from unittest.mock import patch
import json
import jwt
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.utils import timezone
from rest_framework import status
from ee.models.vercel.vercel_installation import VercelInstallation
from ee.models.vercel.vercel_resource import VercelResource
from posthog.models.team.team import Team
from posthog.test.base import APIBaseTest


@patch("ee.api.authentication.get_vercel_jwks")
class TestVercelResourceAPI(APIBaseTest):
    """Test Vercel Resource API functionality"""

    def setUp(self):
        super().setUp()
        self.installation_id = "inst_123456789"
        self.account_id = "acc987654321"
        self.user_id = "111222333abc"

        self.installation = VercelInstallation.objects.create(
            organization=self.organization,
            installation_id=self.installation_id,
            billing_plan_id="free",
            upsert_data={"scopes": ["read", "write"], "access_token": "test_token", "token_type": "Bearer"},
        )

        self.test_team = Team.objects.create_with_data(
            initiating_user=None,
            organization=self.organization,
            name="Test Resource Team",
        )

        self.resource = VercelResource.objects.create(
            team=self.test_team,
            installation=self.installation,
            resource_id=str(self.test_team.pk),
            config={
                "productId": "posthog",
                "name": "Test Resource Team",
                "metadata": {"key": "value"},
                "billingPlanId": "free",
            },
        )

        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.public_key = self.private_key.public_key()

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

    def _create_jwt_token(self, payload: dict, headers: dict | None = None) -> str:
        """Create a real JWT token for testing"""
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

    def _get_auth_headers(self, auth_type: str = "user") -> dict:
        """Create authentication headers for API requests"""
        if auth_type == "user":
            payload = self._create_user_auth_payload()
        else:
            raise ValueError("Only user auth type supported in this test")

        token = self._create_jwt_token(payload)
        return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_VERCEL_AUTH": auth_type}

    def test_partial_update_resource_name(self, mock_get_jwks):
        """Test updating resource name via partial_update"""
        mock_get_jwks.return_value = self.mock_jwks

        headers = self._get_auth_headers("user")

        # Update just the name
        update_data = {"name": "Updated Resource Name"}

        response = self.client.patch(
            f"/api/vercel/v1/installations/{self.installation_id}/resources/{self.resource.id}/",
            data=json.dumps(update_data),
            content_type="application/json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data["name"], "Updated Resource Name")
        self.assertEqual(data["id"], str(self.resource.pk))
        self.assertEqual(data["status"], "ready")
        self.assertIn("secrets", data)
        self.assertIn("billingPlan", data)

        self.resource.refresh_from_db()
        self.test_team.refresh_from_db()
        self.assertEqual(self.resource.config["name"], "Updated Resource Name")
        self.assertEqual(self.test_team.name, "Updated Resource Name")

    def test_partial_update_resource_metadata(self, mock_get_jwks):
        """Test updating resource metadata via partial_update"""
        mock_get_jwks.return_value = self.mock_jwks

        headers = self._get_auth_headers("user")

        update_data = {"metadata": {"new_key": "new_value", "updated": True}}

        response = self.client.patch(
            f"/api/vercel/v1/installations/{self.installation_id}/resources/{self.resource.id}/",
            data=json.dumps(update_data),
            content_type="application/json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data["metadata"]["new_key"], "new_value")
        self.assertTrue(data["metadata"]["updated"])

        self.resource.refresh_from_db()
        self.assertEqual(self.resource.config["metadata"]["new_key"], "new_value")
        self.assertTrue(self.resource.config["metadata"]["updated"])
