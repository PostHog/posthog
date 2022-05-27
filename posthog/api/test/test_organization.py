from rest_framework import status

from posthog.models import Organization, OrganizationMembership, Team
from posthog.test.base import APIBaseTest


class TestOrganizationAPI(APIBaseTest):

    # Retrieving organization

    def test_get_current_organization(self):
        response = self.client.get("/api/organizations/@current")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["id"], str(self.organization.id))
        # By default, setup state is marked as completed
        self.assertEqual(response_data["available_features"], [])

        # DEPRECATED attributes
        self.assertNotIn("personalization", response_data)
        self.assertNotIn("setup", response_data)

    def test_get_current_team_fields(self):
        self.organization.setup_section_2_completed = False
        self.organization.save()
        Team.objects.create(organization=self.organization, is_demo=True, ingested_event=True)
        Team.objects.create(organization=self.organization, completed_snippet_onboarding=True)
        self.team.is_demo = True
        self.team.save()

        response_data = self.client.get("/api/organizations/@current").json()

        self.assertEqual(response_data["id"], str(self.organization.id))

    # Creating organizations

    def test_cant_create_organization_without_valid_license_on_self_hosted(self):
        with self.settings(MULTI_TENANCY=False):
            response = self.client.post("/api/organizations/", {"name": "Test"})
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertEqual(
                response.json(),
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

    # Updating organizations

    def test_update_organization_if_admin(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.organization.name = self.CONFIG_ORGANIZATION_NAME
        self.organization.is_member_join_email_enabled = True
        self.organization.save()

        response_rename = self.client.patch(f"/api/organizations/{self.organization.id}", {"name": "QWERTY"})
        response_email = self.client.patch(
            f"/api/organizations/{self.organization.id}", {"is_member_join_email_enabled": False}
        )

        self.assertEqual(response_rename.status_code, status.HTTP_200_OK)
        self.assertEqual(response_email.status_code, status.HTTP_200_OK)

        self.organization.refresh_from_db()
        self.assertEqual(self.organization.name, "QWERTY")
        self.assertEqual(self.organization.is_member_join_email_enabled, False)

    def test_update_organization_if_owner(self):
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()
        self.organization.name = self.CONFIG_ORGANIZATION_NAME
        self.organization.is_member_join_email_enabled = True
        self.organization.save()

        response_rename = self.client.patch(f"/api/organizations/{self.organization.id}", {"name": "QWERTY"})
        response_email = self.client.patch(
            f"/api/organizations/{self.organization.id}", {"is_member_join_email_enabled": False}
        )

        self.assertEqual(response_rename.status_code, status.HTTP_200_OK)
        self.assertEqual(response_email.status_code, status.HTTP_200_OK)

        self.organization.refresh_from_db()
        self.assertEqual(self.organization.name, "QWERTY")
        self.assertEqual(self.organization.is_member_join_email_enabled, False)

    def test_cannot_update_organization_if_not_owner_or_admin(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response_rename = self.client.patch(f"/api/organizations/{self.organization.id}", {"name": "ASDFG"})
        response_email = self.client.patch(
            f"/api/organizations/{self.organization.id}", {"is_member_join_email_enabled": False}
        )
        self.assertEqual(response_rename.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response_email.status_code, status.HTTP_403_FORBIDDEN)
        self.organization.refresh_from_db()
        self.assertNotEqual(self.organization.name, "ASDFG")


def create_organization(name: str) -> Organization:
    """
    Helper that just creates an organization. It currently uses the orm, but we
    could use either the api, or django admin to create, to get better parity
    with real world scenarios.
    """
    return Organization.objects.create(name=name)
