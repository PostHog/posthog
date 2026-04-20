from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models.organization_integration import OrganizationIntegration


class TestOrganizationIntegrationViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.integration_vercel = OrganizationIntegration.objects.create(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id="test-vercel-id",
            config={
                "account": {
                    "name": "Test Vercel Account",
                    "url": "https://vercel.com/test-account",
                }
            },
            created_by=self.user,
        )

    def test_list_organization_integrations_success(self):
        url = f"/api/organizations/{self.organization.id}/integrations/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)

        integration_data = response.json()["results"][0]
        self.assertEqual(integration_data["kind"], "vercel")
        self.assertEqual(integration_data["integration_id"], "test-vercel-id")
        self.assertEqual(integration_data["config"]["account"]["name"], "Test Vercel Account")
        self.assertEqual(integration_data["created_by"]["id"], self.user.id)
        self.assertIn("created_at", integration_data)
        self.assertIn("updated_at", integration_data)

    def test_list_organization_integrations_multiple_integrations(self):
        OrganizationIntegration.objects.create(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id="second-vercel-id",
            config={"account": {"name": "Second Account"}},
            created_by=self.user,
        )

        url = f"/api/organizations/{self.organization.id}/integrations/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 2)

    def test_list_organization_integrations_scoped_to_organization(self):
        from posthog.models import Organization

        other_org = Organization.objects.create(name="Other Organization")
        OrganizationIntegration.objects.create(
            organization=other_org,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id="other-org-integration",
            config={},
            created_by=self.user,
        )

        url = f"/api/organizations/{self.organization.id}/integrations/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["integration_id"], "test-vercel-id")

    def test_list_organization_integrations_unauthorized(self):
        self.client.logout()

        url = f"/api/organizations/{self.organization.id}/integrations/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retrieve_organization_integration_success(self):
        url = f"/api/organizations/{self.organization.id}/integrations/{self.integration_vercel.id}/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(self.integration_vercel.id))
        self.assertEqual(response.json()["kind"], "vercel")
        self.assertEqual(response.json()["integration_id"], "test-vercel-id")

    def test_retrieve_organization_integration_not_found(self):
        url = f"/api/organizations/{self.organization.id}/integrations/00000000-0000-0000-0000-000000000000/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_retrieve_organization_integration_unauthorized(self):
        self.client.logout()

        url = f"/api/organizations/{self.organization.id}/integrations/{self.integration_vercel.id}/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_delete_organization_integration_not_supported(self):
        url = f"/api/organizations/{self.organization.id}/integrations/{self.integration_vercel.id}/"
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertTrue(OrganizationIntegration.objects.filter(id=self.integration_vercel.id).exists())

    def test_create_organization_integration_not_supported(self):
        url = f"/api/organizations/{self.organization.id}/integrations/"
        data = {
            "kind": "vercel",
            "integration_id": "new-integration",
            "config": {},
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_update_organization_integration_not_supported(self):
        url = f"/api/organizations/{self.organization.id}/integrations/{self.integration_vercel.id}/"
        data = {"config": {"updated": True}}
        response = self.client.patch(url, data)

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
