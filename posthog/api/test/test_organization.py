from posthog.models.organization import Organization, OrganizationMembership

from .base import APIBaseTest


class TestOrganizationAPI(APIBaseTest):
    def test_no_create_organization_without_license_selfhosted(self):
        with self.settings(MULTI_TENANCY=False):
            response = self.client.post("/api/organizations/", {"name": "Test"})
            self.assertEqual(response.status_code, 403)
            self.assertEqual(
                response.data,
                {
                    "attr": None,
                    "code": "permission_denied",
                    "detail": "You must upgrade your PostHog plan to be able to create and manage multiple organizations.",
                    "type": "authentication_error",
                },
            )
            self.assertEqual(Organization.objects.count(), 1)
            response = self.client.post("/api/organizations/", {"name": "Test"})
            self.assertEqual(Organization.objects.count(), 1)

    def test_rename_organization_without_license_if_admin(self):
        response = self.client.patch(f"/api/organizations/{self.organization.id}", {"name": "QWERTY"})
        self.assertEqual(response.status_code, 200)
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.name, "QWERTY")
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.patch(f"/api/organizations/{self.organization.id}", {"name": "ASDFG"})
        self.assertEqual(response.status_code, 403)
