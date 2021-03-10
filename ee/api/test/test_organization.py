from typing import cast

from rest_framework import status

from ee.api.test.base import APILicensedTest
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team import Team


class TestOrganizationEnterpriseAPI(APILicensedTest):
    def test_create_organization(self):
        response = self.client.post("/api/organizations/", {"name": "Test"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Organization.objects.count(), 2)
        response_data = response.json()
        self.assertEqual(response_data.get("name"), "Test")
        self.assertEqual(OrganizationMembership.objects.filter(organization_id=response_data.get("id")).count(), 1)
        self.assertEqual(
            OrganizationMembership.objects.get(organization_id=response_data.get("id"), user=self.user).level,
            OrganizationMembership.Level.OWNER,
        )

    def test_delete_second_managed_organization(self):
        organization, _, team = Organization.objects.bootstrap(self.user, name="X")
        self.assertTrue(Organization.objects.filter(id=organization.id).exists())
        self.assertTrue(Team.objects.filter(id=team.id).exists())
        response = self.client.delete(f"/api/organizations/{organization.id}")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Organization.objects.filter(id=organization.id).exists())
        self.assertFalse(Team.objects.filter(id=team.id).exists())

    def test_delete_last_organization(self):
        org_id = self.organization.id
        self.assertTrue(Organization.objects.filter(id=org_id).exists())

        response = self.client.delete(f"/api/organizations/{org_id}")

        self.assertEqual(response.status_code, 204, "Did not successfully delete last organization on the instance")
        self.assertFalse(Organization.objects.filter(id=org_id).exists())
        self.assertFalse(Organization.objects.exists())

        response_bis = self.client.delete(f"/api/organizations/{org_id}")

        self.assertEqual(response_bis.status_code, 404, "Did not return a 404 on trying to delete a nonexistent org")

    def test_no_delete_organization_not_owning(self):
        for level in (OrganizationMembership.Level.MEMBER, OrganizationMembership.Level.ADMIN):
            self.organization_membership.level = level
            self.organization_membership.save()
            response = self.client.delete(f"/api/organizations/{self.organization.id}")
            potential_err_message = f"Somehow managed to delete the org as a level {level} (which is not owner)"
            self.assertEqual(
                response.data,
                {
                    "attr": None,
                    "detail": "Your organization access level is insufficient.",
                    "code": "permission_denied",
                    "type": "authentication_error",
                },
                potential_err_message,
            )
            self.assertEqual(response.status_code, 403, potential_err_message)
            self.assertTrue(self.organization.name, self.CONFIG_ORGANIZATION_NAME)

    def test_delete_organization_owning(self):
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()
        response = self.client.delete(f"/api/organizations/{self.organization.id}")
        potential_err_message = f"Somehow did not delete the org as the owner"
        self.assertEqual(response.status_code, 204, potential_err_message)
        self.assertFalse(Organization.objects.filter(id=self.organization.id).exists())

    def test_no_delete_organization_not_belonging_to(self):
        for level in OrganizationMembership.Level:
            self.organization_membership.level = level
            self.organization_membership.save()
            organization = Organization.objects.create(name="Some Other Org")
            response = self.client.delete(f"/api/organizations/{organization.id}")
            potential_err_message = f"Somehow managed to delete someone else's org as a level {level} in own org"
            self.assertEqual(
                response.data,
                {"attr": None, "detail": "Not found.", "code": "not_found", "type": "invalid_request"},
                potential_err_message,
            )
            self.assertEqual(response.status_code, 404, potential_err_message)
            self.assertTrue(Organization.objects.filter(id=organization.id).exists(), potential_err_message)

    def test_rename_org(self):
        for level in OrganizationMembership.Level:
            self.organization_membership.level = level
            self.organization_membership.save()
            response = self.client.patch(f"/api/organizations/{self.organization.id}", {"name": "Woof"})
            self.organization.refresh_from_db()
            if level < OrganizationMembership.Level.ADMIN:
                potential_err_message = f"Somehow managed to rename the org as a level {level} (which is below admin)"
                self.assertEqual(
                    response.data,
                    {
                        "attr": None,
                        "detail": "Your organization access level is insufficient.",
                        "code": "permission_denied",
                        "type": "authentication_error",
                    },
                    potential_err_message,
                )
                self.assertEqual(response.status_code, 403, potential_err_message)
                self.assertTrue(self.organization.name, self.CONFIG_ORGANIZATION_NAME)
            else:
                potential_err_message = f"Somehow did not rename the org as a level {level} (which is at least admin)"
                self.assertEqual(response.status_code, 200, potential_err_message)
                self.assertTrue(self.organization.name, "Woof")

    def test_no_rename_organization_not_belonging_to(self):
        for level in OrganizationMembership.Level:
            self.organization_membership.level = level
            self.organization_membership.save()
            organization = Organization.objects.create(name="Meow")
            response = self.client.patch(f"/api/organizations/{organization.id}", {"name": "Mooooooooo"})
            potential_err_message = f"Somehow managed to rename someone else's org as a level {level} in own org"
            self.assertEqual(
                response.data,
                {"attr": None, "detail": "Not found.", "code": "not_found", "type": "invalid_request"},
                potential_err_message,
            )
            self.assertEqual(response.status_code, 404, potential_err_message)
            organization.refresh_from_db()
            self.assertTrue(organization.name, "Meow")
