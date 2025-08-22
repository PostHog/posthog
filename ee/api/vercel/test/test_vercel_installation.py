from unittest.mock import patch
import json
from rest_framework import status
from ee.api.vercel.test.base import VercelTestBase
from posthog.models.organization_integration import OrganizationIntegration


@patch("ee.api.authentication.get_vercel_jwks")
class TestVercelInstallationAPI(VercelTestBase):
    def test_retrieve_installation(self, mock_get_jwks):
        mock_get_jwks.return_value = self.mock_jwks

        headers = self._get_auth_headers("system")

        response = self.client.get(f"/api/vercel/v1/installations/{self.installation_id}/", **headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("billingplan", data)
        self.assertEqual(data["billingplan"]["id"], "free")

    def test_update_installation(self, mock_get_jwks):
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

        self.assertNotEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_partial_update_installation(self, mock_get_jwks):
        mock_get_jwks.return_value = self.mock_jwks

        headers = self._get_auth_headers("user")

        invalid_data = {
            "scopes": [],
            "credentials": {"access_token": "token"},
        }

        response = self.client.patch(
            f"/api/vercel/v1/installations/{self.installation_id}/",
            data=json.dumps(invalid_data),
            content_type="application/json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_installation(self, mock_get_jwks):
        mock_get_jwks.return_value = self.mock_jwks

        headers = self._get_auth_headers("user")

        response = self.client.delete(f"/api/vercel/v1/installations/{self.installation_id}/", **headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("finalized", data)
        self.assertFalse(data["finalized"])
        self.assertFalse(
            OrganizationIntegration.objects.filter(
                kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL, integration_id=self.installation_id
            ).exists()
        )

    def test_system_auth_retrieve_installation(self, mock_get_jwks):
        mock_get_jwks.return_value = self.mock_jwks

        headers = self._get_auth_headers("system")

        response = self.client.get(f"/api/vercel/v1/installations/{self.installation_id}/", **headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("billingplan", data)
        self.assertEqual(data["billingplan"]["id"], "free")
