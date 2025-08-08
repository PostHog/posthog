from unittest.mock import patch
import json
from rest_framework import status
from ee.models.vercel.vercel_resource import VercelResource
from posthog.models.team.team import Team
from ee.api.vercel.test.base import VercelTestBase


@patch("ee.api.authentication.get_vercel_jwks")
class TestVercelResourceAPI(VercelTestBase):
    def setUp(self):
        super().setUp()

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

    def test_partial_update_resource_name(self, mock_get_jwks):
        mock_get_jwks.return_value = self.mock_jwks

        headers = self._get_auth_headers("user")

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
        self.assertEqual(self.resource.config["name"], "Updated Resource Name")

    def test_partial_update_resource_metadata(self, mock_get_jwks):
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
