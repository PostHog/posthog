from posthog.models.organization import Organization

from .base import APIBaseTest


class TestOrganizationAPI(APIBaseTest):
    def test_no_create_organization_without_license_selfhosted(self):
        response = self.client.post("/api/organizations/", {"name": "Test"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.data,
            {
                "attr": None,
                "code": "permission_denied",
                "detail": "Your organization access level is insufficient.",
                "type": "authentication_error",
            },
        )
        self.assertEqual(Organization.objects.count(), 1)
        response = self.client.post("/api/organizations/", {"name": "Test"})
        self.assertEqual(Organization.objects.count(), 1)

    def test_rename_organization_without_license(self):
        response = self.client.patch("/api/organizations/@current", {"name": "QWERTY"})
        self.assertEqual(response.status_code, 200)
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.name, "QWERTY")
