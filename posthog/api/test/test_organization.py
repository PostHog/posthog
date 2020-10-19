from posthog.models.organization import Organization

from .base import APIBaseTest


class TestOrganizationAPI(APIBaseTest):
    def test_no_create_organization_without_license(self):
        response = self.client.post("/api/organizations/", {"name": "Test"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Organization.objects.count(), 1)
        response = self.client.post("/api/organizations/", {"name": "Test"})
        self.assertEqual(Organization.objects.count(), 1)
