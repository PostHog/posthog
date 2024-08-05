from rest_framework.status import (
    HTTP_200_OK,
    HTTP_204_NO_CONTENT,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
)

from ee.api.test.base import APILicensedTest
from ee.models.explicit_team_membership import ExplicitTeamMembership
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User
from posthog.test.base import FuzzyInt


class TestProjectEnterpriseAPI(APILicensedTest):
    CLASS_DATA_LEVEL_SETUP = False

    # Creating projects

    def test_create_project(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        response = self.client.post("/api/projects/", {"name": "Test"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Team.objects.count(), 2)
        response_data = response.json()
        self.assertDictContainsSubset(
            {
                "name": "Test",
                "access_control": False,
                "effective_membership_level": OrganizationMembership.Level.ADMIN,
            },
            response_data,
        )
        self.assertEqual(self.organization.teams.count(), 2)

    def test_non_admin_cannot_create_project(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        count = Team.objects.count()
        response = self.client.post("/api/projects/", {"name": "Test"})
        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)
        self.assertEqual(Team.objects.count(), count)
        self.assertEqual(
            response.json(),
            self.permission_denied_response("Your organization access level is insufficient."),
        )

    def test_create_demo_project(self, *args):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        response = self.client.post("/api/projects/", {"name": "Hedgebox", "is_demo": True})
        self.assertEqual(Team.objects.count(), 2)
        self.assertEqual(response.status_code, 201)
        response_data = response.json()
        self.assertDictContainsSubset(
            {
                "name": "Hedgebox",
                "access_control": False,
                "effective_membership_level": OrganizationMembership.Level.ADMIN,
            },
            response_data,
        )
        self.assertEqual(self.organization.teams.count(), 2)

    def test_create_two_demo_projects(self, *args):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        response = self.client.post("/api/projects/", {"name": "Hedgebox", "is_demo": True})
        self.assertEqual(Team.objects.count(), 2)
        self.assertEqual(response.status_code, 201)
        response_data = response.json()
        self.assertDictContainsSubset(
            {
                "name": "Hedgebox",
                "access_control": False,
                "effective_membership_level": OrganizationMembership.Level.ADMIN,
            },
            response_data,
        )
        response_2 = self.client.post("/api/projects/", {"name": "Hedgebox", "is_demo": True})
        self.assertEqual(Team.objects.count(), 2)
        response_2_data = response_2.json()
        self.assertDictContainsSubset(
            {
                "type": "authentication_error",
                "code": "permission_denied",
                "detail": "You must upgrade your PostHog plan to be able to create and manage multiple projects or environments.",
            },
            response_2_data,
        )
        self.assertEqual(self.organization.teams.count(), 2)

    def test_user_that_does_not_belong_to_an_org_cannot_create_a_project(self):
        user = User.objects.create(email="no_org@posthog.com")
        self.client.force_login(user)

        response = self.client.post("/api/projects/", {"name": "Test"})
        self.assertEqual(response.status_code, HTTP_404_NOT_FOUND, response.content)
        self.assertEqual(
            response.json(),
            {
                "type": "invalid_request",
                "code": "not_found",
                "detail": "You need to belong to an organization.",
                "attr": None,
            },
        )

    def test_user_create_project_for_org_via_url(self):
        # Set both current and new org to high enough membership level
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        current_org, _, _ = Organization.objects.bootstrap(self.user, name="other_org")
        other_org = self.organization  # Bootstrapping above sets it to the current org

        assert current_org.id == self.user.current_organization_id
        response = self.client.post(f"/api/organizations/{current_org.id}/projects/", {"name": "Via current org"})
        self.assertEqual(response.status_code, 201)
        assert response.json()["organization"] == str(current_org.id)

        assert other_org.id != self.user.current_organization_id
        response = self.client.post(f"/api/organizations/{other_org.id}/projects/", {"name": "Via path org"})
        self.assertEqual(response.status_code, 201, msg=response.json())
        assert response.json()["organization"] == str(other_org.id)

    def test_user_cannot_create_project_in_org_without_access(self):
        _, _, _ = Organization.objects.bootstrap(self.user, name="other_org")
        other_org = self.organization  # Bootstrapping above sets it to the current org

        assert other_org.id != self.user.current_organization_id
        response = self.client.post(f"/api/organizations/{other_org.id}/projects/", {"name": "Via path org"})
        self.assertEqual(response.status_code, 403, msg=response.json())
        assert response.json() == self.permission_denied_response("Your organization access level is insufficient.")

    # Deleting projects

    def test_delete_team_as_org_admin_allowed(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        response = self.client.delete(f"/api/projects/{self.team.id}")
        self.assertEqual(response.status_code, HTTP_204_NO_CONTENT)
        self.assertEqual(Team.objects.filter(organization=self.organization).count(), 0)

    def test_delete_team_as_org_member_forbidden(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.delete(f"/api/projects/{self.team.id}")
        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)
        self.assertEqual(Team.objects.filter(organization=self.organization).count(), 1)

    def test_delete_open_team_as_org_member_but_project_admin_forbidden(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        ExplicitTeamMembership.objects.create(
            team=self.team,
            parent_membership=self.organization_membership,
            level=ExplicitTeamMembership.Level.ADMIN,
        )
        response = self.client.delete(f"/api/projects/{self.team.id}")
        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)
        self.assertEqual(Team.objects.filter(organization=self.organization).count(), 1)

    def test_delete_private_team_as_org_member_but_project_admin_allowed(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.team.access_control = True
        self.team.save()
        ExplicitTeamMembership.objects.create(
            team=self.team,
            parent_membership=self.organization_membership,
            level=ExplicitTeamMembership.Level.ADMIN,
        )
        response = self.client.delete(f"/api/projects/{self.team.id}")
        self.assertEqual(response.status_code, HTTP_204_NO_CONTENT)
        self.assertEqual(Team.objects.filter(organization=self.organization).count(), 0)

    def test_delete_second_team_as_org_admin_allowed(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        team = Team.objects.create(organization=self.organization)
        response = self.client.delete(f"/api/projects/{team.id}")
        self.assertEqual(response.status_code, HTTP_204_NO_CONTENT)
        self.assertEqual(Team.objects.filter(organization=self.organization).count(), 1)

    def test_no_delete_team_not_administrating_organization(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        team = Team.objects.create(organization=self.organization)
        response = self.client.delete(f"/api/projects/{team.id}")
        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)
        self.assertEqual(Team.objects.filter(organization=self.organization).count(), 2)

    def test_no_delete_team_not_belonging_to_organization(self):
        team_1 = Organization.objects.bootstrap(None)[2]
        response = self.client.delete(f"/api/projects/{team_1.id}")
        self.assertEqual(response.status_code, HTTP_404_NOT_FOUND)
        self.assertTrue(Team.objects.filter(id=team_1.id).exists())
        organization, _, _ = User.objects.bootstrap("X", "someone@x.com", "qwerty", "Someone")
        team_2 = Team.objects.create(organization=organization)
        response = self.client.delete(f"/api/projects/{team_2.id}")
        self.assertEqual(response.status_code, HTTP_404_NOT_FOUND)
        self.assertEqual(Team.objects.filter(organization=organization).count(), 2)

    # Updating projects

    def test_rename_project_as_org_member_allowed(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.patch(f"/api/projects/@current/", {"name": "Erinaceus europaeus"})
        self.team.refresh_from_db()

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(self.team.name, "Erinaceus europaeus")

    def test_rename_private_project_as_org_member_forbidden(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.team.access_control = True
        self.team.save()

        response = self.client.patch(f"/api/projects/@current/", {"name": "Acherontia atropos"})
        self.team.refresh_from_db()

        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)
        self.assertEqual(self.team.name, "Default project")

    def test_rename_private_project_current_as_org_outsider_forbidden(self):
        self.organization_membership.delete()

        response = self.client.patch(f"/api/projects/@current/", {"name": "Acherontia atropos"})
        self.team.refresh_from_db()

        self.assertEqual(response.status_code, HTTP_404_NOT_FOUND)

    def test_rename_private_project_id_as_org_outsider_forbidden(self):
        self.organization_membership.delete()

        response = self.client.patch(f"/api/projects/{self.team.id}/", {"name": "Acherontia atropos"})
        self.team.refresh_from_db()

        self.assertEqual(response.status_code, HTTP_404_NOT_FOUND)

    def test_rename_private_project_as_org_member_and_project_member_allowed(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.team.access_control = True
        self.team.save()
        ExplicitTeamMembership.objects.create(
            team=self.team,
            parent_membership=self.organization_membership,
            level=ExplicitTeamMembership.Level.MEMBER,
        )

        response = self.client.patch(f"/api/projects/@current/", {"name": "Acherontia atropos"})
        self.team.refresh_from_db()

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(self.team.name, "Acherontia atropos")

    def test_enable_access_control_as_org_member_forbidden(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.patch(f"/api/projects/@current/", {"access_control": True})
        self.team.refresh_from_db()

        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)
        self.assertFalse(self.team.access_control)

    def test_enable_access_control_as_org_admin_allowed(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.patch(f"/api/projects/@current/", {"access_control": True})
        self.team.refresh_from_db()

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertTrue(self.team.access_control)

    def test_enable_access_control_as_org_member_and_project_admin_forbidden(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        ExplicitTeamMembership.objects.create(
            team=self.team,
            parent_membership=self.organization_membership,
            level=ExplicitTeamMembership.Level.ADMIN,
        )

        response = self.client.patch(f"/api/projects/@current/", {"access_control": True})
        self.team.refresh_from_db()

        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)
        self.assertFalse(self.team.access_control)

    def test_disable_access_control_as_org_member_forbidden(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.team.access_control = True
        self.team.save()

        response = self.client.patch(f"/api/projects/@current/", {"access_control": False})
        self.team.refresh_from_db()

        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)
        self.assertTrue(self.team.access_control)

    def test_disable_access_control_as_org_member_and_project_admin_forbidden(self):
        # Only org-wide admins+ should be allowed to make the project open,
        # because if a project-specific admin who is only an org member did it, they wouldn't be able to reenable it
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.team.access_control = True
        self.team.save()
        ExplicitTeamMembership.objects.create(
            team=self.team,
            parent_membership=self.organization_membership,
            level=ExplicitTeamMembership.Level.ADMIN,
        )

        response = self.client.patch(f"/api/projects/@current/", {"access_control": False})
        self.team.refresh_from_db()

        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)
        self.assertTrue(self.team.access_control)

    def test_disable_access_control_as_org_admin_allowed(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.team.access_control = True
        self.team.save()

        response = self.client.patch(f"/api/projects/@current/", {"access_control": False})
        self.team.refresh_from_db()

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertFalse(self.team.access_control)

    def test_can_update_and_retrieve_person_property_names_excluded_from_correlation(self):
        response = self.client.patch(
            f"/api/projects/@current/",
            {"correlation_config": {"excluded_person_property_names": ["$os"]}},
        )
        self.assertEqual(response.status_code, HTTP_200_OK)

        response = self.client.get(f"/api/projects/@current/")
        self.assertEqual(response.status_code, HTTP_200_OK)

        response_data = response.json()

        self.assertDictContainsSubset(
            {"correlation_config": {"excluded_person_property_names": ["$os"]}},
            response_data,
        )

    # Fetching projects

    def test_fetch_team_as_org_admin_works(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.get(f"/api/projects/@current/")
        response_data = response.json()

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertDictContainsSubset(
            {
                "name": "Default project",
                "access_control": False,
                "effective_membership_level": OrganizationMembership.Level.ADMIN,
            },
            response_data,
        )

    def test_fetch_team_as_org_member_works(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.get(f"/api/projects/@current/")
        response_data = response.json()

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertDictContainsSubset(
            {
                "name": "Default project",
                "access_control": False,
                "effective_membership_level": OrganizationMembership.Level.MEMBER,
            },
            response_data,
        )

    def test_fetch_private_team_as_org_member(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.team.access_control = True
        self.team.save()

        response = self.client.get(f"/api/projects/@current/")
        response_data = response.json()

        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.permission_denied_response("You don't have sufficient permissions in the project."),
            response_data,
        )

    def test_fetch_private_team_as_org_member_and_project_member(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.team.access_control = True
        self.team.save()
        ExplicitTeamMembership.objects.create(
            team=self.team,
            parent_membership=self.organization_membership,
            level=ExplicitTeamMembership.Level.MEMBER,
        )

        response = self.client.get(f"/api/projects/@current/")
        response_data = response.json()

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertDictContainsSubset(
            {
                "name": "Default project",
                "access_control": True,
                "effective_membership_level": OrganizationMembership.Level.MEMBER,
            },
            response_data,
        )

    def test_fetch_private_team_as_org_member_and_project_admin(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.team.access_control = True
        self.team.save()
        ExplicitTeamMembership.objects.create(
            team=self.team,
            parent_membership=self.organization_membership,
            level=ExplicitTeamMembership.Level.ADMIN,
        )

        response = self.client.get(f"/api/projects/@current/")
        response_data = response.json()

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertDictContainsSubset(
            {
                "name": "Default project",
                "access_control": True,
                "effective_membership_level": OrganizationMembership.Level.ADMIN,
            },
            response_data,
        )

    def test_fetch_team_as_org_outsider(self):
        self.organization_membership.delete()
        response = self.client.get(f"/api/projects/@current/")
        response_data = response.json()

        self.assertEqual(response.status_code, HTTP_404_NOT_FOUND)
        self.assertEqual(self.not_found_response(), response_data)

    def test_fetch_nonexistent_team(self):
        response = self.client.get(f"/api/projects/234444/")
        response_data = response.json()

        self.assertEqual(response.status_code, HTTP_404_NOT_FOUND)
        self.assertEqual(self.not_found_response(), response_data)

    def test_list_teams_restricted_ones_hidden(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        Team.objects.create(
            organization=self.organization,
            name="Other",
            access_control=True,
        )

        # The other team should not be returned as it's restricted for the logged-in user
        projects_response = self.client.get(f"/api/projects/")

        # 9 (above):
        with self.assertNumQueries(FuzzyInt(9, 10)):
            current_org_response = self.client.get(f"/api/organizations/{self.organization.id}/")

        self.assertEqual(projects_response.status_code, HTTP_200_OK)
        self.assertEqual(
            projects_response.json().get("results"),
            [
                {
                    "id": self.team.id,
                    "uuid": str(self.team.uuid),
                    "organization": str(self.organization.id),
                    "api_token": self.team.api_token,
                    "name": self.team.name,
                    "completed_snippet_onboarding": False,
                    "has_completed_onboarding_for": {"product_analytics": True},
                    "ingested_event": False,
                    "is_demo": False,
                    "timezone": "UTC",
                    "access_control": False,
                }
            ],
        )
        self.assertEqual(current_org_response.status_code, HTTP_200_OK)
        self.assertEqual(
            current_org_response.json().get("teams"),
            [
                {
                    "id": self.team.id,
                    "uuid": str(self.team.uuid),
                    "organization": str(self.organization.id),
                    "api_token": self.team.api_token,
                    "name": self.team.name,
                    "completed_snippet_onboarding": False,
                    "has_completed_onboarding_for": {"product_analytics": True},
                    "ingested_event": False,
                    "is_demo": False,
                    "timezone": "UTC",
                    "access_control": False,
                }
            ],
        )
