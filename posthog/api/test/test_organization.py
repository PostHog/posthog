from rest_framework import status
from unittest.mock import patch, ANY

from posthog.models import Organization, OrganizationMembership, Team
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal
from posthog.test.base import APIBaseTest
from posthog.api.organization import OrganizationSerializer
from rest_framework.test import APIRequestFactory
from posthog.user_permissions import UserPermissions


class TestOrganizationAPI(APIBaseTest):
    # Retrieving organization

    def test_get_current_organization(self):
        response = self.client.get("/api/organizations/@current")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["id"], str(self.organization.id))
        # By default, setup state is marked as completed
        self.assertEqual(response_data["available_product_features"], [])

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
        with self.is_cloud(False):
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

    def test_cant_create_organization_with_custom_plugin_level(self):
        with self.is_cloud(True):
            response = self.client.post("/api/organizations/", {"name": "Test", "plugins_access_level": 6})
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(Organization.objects.count(), 2)
            self.assertEqual(response.json()["plugins_access_level"], 3)

    # Updating organizations

    def test_update_organization_if_admin(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.organization.name = self.CONFIG_ORGANIZATION_NAME
        self.organization.is_member_join_email_enabled = True
        self.organization.save()

        response_rename = self.client.patch(f"/api/organizations/{self.organization.id}", {"name": "QWERTY"})
        response_email = self.client.patch(
            f"/api/organizations/{self.organization.id}",
            {"is_member_join_email_enabled": False},
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
            f"/api/organizations/{self.organization.id}",
            {"is_member_join_email_enabled": False},
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
            f"/api/organizations/{self.organization.id}",
            {"is_member_join_email_enabled": False},
        )
        self.assertEqual(response_rename.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response_email.status_code, status.HTTP_403_FORBIDDEN)
        self.organization.refresh_from_db()
        self.assertNotEqual(self.organization.name, "ASDFG")

    def test_cant_update_plugins_access_level(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.organization.plugins_access_level = 3
        self.organization.save()

        response = self.client.patch(f"/api/organizations/{self.organization.id}", {"plugins_access_level": 9})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.plugins_access_level, 3)

    @patch("posthoganalytics.capture")
    def test_enforce_2fa_for_everyone(self, mock_capture):
        # Only admins should be able to enforce 2fa
        response = self.client.patch(f"/api/organizations/{self.organization.id}/", {"enforce_2fa": True})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.patch(f"/api/organizations/{self.organization.id}/", {"enforce_2fa": True})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.organization.refresh_from_db()
        self.assertEqual(self.organization.enforce_2fa, True)

        # Verify the capture event was called correctly
        mock_capture.assert_any_call(
            self.user.distinct_id,
            "organization 2fa enforcement toggled",
            properties={
                "enabled": True,
                "organization_id": str(self.organization.id),
                "organization_name": self.organization.name,
                "user_role": OrganizationMembership.Level.ADMIN,
            },
            groups={"instance": ANY, "organization": str(self.organization.id)},
        )

    def test_projects_outside_personal_api_key_scoped_organizations_not_listed(self):
        other_org, _, _ = Organization.objects.bootstrap(self.user)
        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="X",
            user=self.user,
            last_used_at="2021-08-25T21:09:14",
            secure_value=hash_key_value(personal_api_key),
            scoped_organizations=[other_org.id],
        )

        response = self.client.get("/api/organizations/", HTTP_AUTHORIZATION=f"Bearer {personal_api_key}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {org["id"] for org in response.json()["results"]},
            {str(other_org.id)},
            "Only the scoped organization should be listed, the other one should be excluded",
        )

    def test_delete_organizations_and_verify_list(self):
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()

        # Create two additional organizations
        org2 = Organization.objects.bootstrap(self.user)[0]
        org3 = Organization.objects.bootstrap(self.user)[0]

        self.user.current_organization_id = self.organization.id
        self.user.save()

        # Verify we start with 3 organizations
        response = self.client.get("/api/organizations/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 3)

        # Delete first organization and verify list
        response = self.client.delete(f"/api/organizations/{org2.id}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        response = self.client.get("/api/organizations/")
        self.assertEqual(len(response.json()["results"]), 2)
        org_ids = {org["id"] for org in response.json()["results"]}
        self.assertEqual(org_ids, {str(self.organization.id), str(org3.id)})

        # Delete second organization and verify list
        response = self.client.delete(f"/api/organizations/{org3.id}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        response = self.client.get("/api/organizations/")
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["id"], str(self.organization.id))

        # Verify we can't delete the last organization
        response = self.client.delete(f"/api/organizations/{self.organization.id}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        response = self.client.get("/api/organizations/")
        self.assertEqual(
            response.json(),
            {
                "type": "invalid_request",
                "code": "not_found",
                "detail": "You need to belong to an organization.",
                "attr": None,
            },
        )


def create_organization(name: str) -> Organization:
    """
    Helper that just creates an organization. It currently uses the orm, but we
    could use either the api, or django admin to create, to get better parity
    with real world scenarios.
    """
    return Organization.objects.create(name=name)


class TestOrganizationSerializer(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.request = self.factory.get("/")
        self.request.user = self.user

        # Create a mock view with user_permissions
        class MockView:
            def __init__(self, user_permissions):
                self.user_permissions = user_permissions

        self.view = MockView(UserPermissions(self.user))
        self.context = {"request": self.request, "view": self.view}

    def test_get_teams_with_no_org(self):
        # Clear current_team reference before deleting organization
        self.user.current_team = None
        self.user.current_organization = None
        self.user.save()

        self.organization.delete()

        serializer = OrganizationSerializer(context=self.context)
        self.assertEqual(serializer.user_permissions.team_ids_visible_for_user, [])

    def test_get_teams_with_single_org_no_teams(self):
        # Delete default team created by APIBaseTest
        self.team.delete()

        serializer = OrganizationSerializer(self.organization, context=self.context)
        self.assertEqual(serializer.get_teams(self.organization), [])

    def test_get_teams_with_single_org_multiple_teams(self):
        team2 = Team.objects.create(organization=self.organization, name="Test Team 2")
        team3 = Team.objects.create(organization=self.organization, name="Test Team 3")

        serializer = OrganizationSerializer(self.organization, context=self.context)
        teams = serializer.get_teams(self.organization)

        self.assertEqual(len(teams), 3)
        team_names = {team["name"] for team in teams}
        self.assertEqual(team_names, {self.team.name, team2.name, team3.name})

    def test_get_teams_with_multiple_orgs(self):
        org2, _, _ = Organization.objects.bootstrap(self.user)
        team2 = Team.objects.create(organization=org2, name="Org 2 Team")

        serializer = OrganizationSerializer(self.organization, context=self.context)
        teams1 = serializer.get_teams(self.organization)
        teams2 = serializer.get_teams(org2)

        self.assertEqual(len(teams1), 1)
        self.assertEqual(teams1[0]["name"], self.team.name)

        self.assertEqual(len(teams2), 2)
        self.assertEqual([teams2[0]["name"], teams2[1]["name"]], ["Default project", team2.name])
