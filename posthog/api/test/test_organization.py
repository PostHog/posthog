from unittest.mock import ANY, patch

from rest_framework import status

from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.test.base import APIBaseTest


class TestOrganizationAPI(APIBaseTest):

    # Retrieving organization

    def test_get_current_organization(self):
        self.organization.domain_whitelist = ["hogflix.posthog.com"]
        self.organization.save()

        response = self.client.get("/api/organizations/@current")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["id"], str(self.organization.id))
        # By default, setup state is marked as completed
        self.assertEqual(response_data["available_features"], [])
        self.assertEqual(response_data["domain_whitelist"], ["hogflix.posthog.com"])

    def test_current_organization_on_setup_mode(self):

        self.organization.setup_section_2_completed = False
        self.organization.save()

        response_data = self.client.get("/api/organizations/@current").json()
        self.assertEqual(response_data["setup"]["is_active"], True)
        self.assertEqual(response_data["setup"]["current_section"], 1)
        self.assertEqual(response_data["setup"]["any_project_completed_snippet_onboarding"], False)
        self.assertEqual(response_data["setup"]["non_demo_team_id"], self.team.id)

    def test_get_current_team_fields(self):
        self.organization.setup_section_2_completed = False
        self.organization.save()
        Team.objects.create(organization=self.organization, is_demo=True, ingested_event=True)
        team2 = Team.objects.create(organization=self.organization, completed_snippet_onboarding=True)
        self.team.is_demo = True
        self.team.save()

        response_data = self.client.get("/api/organizations/@current").json()

        self.assertEqual(response_data["id"], str(self.organization.id))
        self.assertEqual(response_data["setup"]["any_project_ingested_events"], False)
        self.assertEqual(response_data["setup"]["any_project_completed_snippet_onboarding"], True)
        self.assertEqual(response_data["setup"]["non_demo_team_id"], team2.id)

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

    def test_update_domain_whitelist_if_admin(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        response = self.client.patch(
            f"/api/organizations/{self.organization.id}", {"domain_whitelist": ["posthog.com", "movies.posthog.com"]}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.domain_whitelist, ["posthog.com", "movies.posthog.com"])

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

    def test_cannot_update_domain_whitelist_if_not_owner_or_admin(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.patch(
            f"/api/organizations/@current", {"domain_whitelist": ["posthog.com", "movies.posthog.com"]}
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.domain_whitelist, [])

    @patch("posthoganalytics.capture")
    def test_member_can_complete_onboarding_setup(self, mock_capture):
        non_admin = User.objects.create(email="non_admin@posthog.com")
        non_admin.join(organization=self.organization)

        for user in [self.user, non_admin]:
            # Any user should be able to complete the onboarding
            self.client.force_login(user)

            self.organization.setup_section_2_completed = False
            self.organization.save()

            response = self.client.post(f"/api/organizations/@current/onboarding")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json()["setup"], {"is_active": False, "current_section": None})
            self.organization.refresh_from_db()
            self.assertEqual(self.organization.setup_section_2_completed, True)

            # Assert the event was reported
            mock_capture.assert_called_with(
                user.distinct_id,
                "onboarding completed",
                properties={"team_members_count": 2},
                groups={
                    "instance": ANY,
                    "organization": str(self.team.organization_id),
                    "project": str(self.team.uuid),
                },
            )

    def test_cannot_complete_onboarding_for_another_org(self):
        _, _, user = User.objects.bootstrap(
            organization_name="Evil, Inc", email="another_one@posthog.com", password="12345678",
        )

        self.client.force_login(user)

        self.organization.setup_section_2_completed = False
        self.organization.save()

        response = self.client.post(f"/api/organizations/{self.organization.id}/onboarding")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response())

        # Object did not change
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.setup_section_2_completed, False)

    @patch("posthoganalytics.capture")
    def test_cannot_complete_already_completed_onboarding(self, mock_capture):
        self.organization.setup_section_2_completed = True
        self.organization.save()

        response = self.client.post(f"/api/organizations/@current/onboarding")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Onboarding already completed.",
                "attr": None,
            },
        )

        # Assert nothing was reported
        mock_capture.assert_not_called()


def create_organization(name: str) -> Organization:
    """
    Helper that just creates an organization. It currently uses the orm, but we
    could use either the api, or django admin to create, to get better parity
    with real world scenarios.
    """
    return Organization.objects.create(name=name)
