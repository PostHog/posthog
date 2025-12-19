from posthog.test.base import FuzzyInt

from posthog.api.test.test_team import EnvironmentToProjectRewriteClient
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.project import Project
from posthog.models.team.team import Team
from posthog.models.user import User

from ee.api.test.test_team import team_enterprise_api_test_factory
from ee.models.rbac.access_control import AccessControl


class TestProjectEnterpriseAPI(team_enterprise_api_test_factory()):
    """
    We inherit from TestTeamEnterpriseAPI, as previously /api/projects/ referred to the Team model, which used to mean "project".
    Now as Team means "environment" and Project is separate, we must ensure backward compatibility of /api/projects/.
    At the same time, this class is where we can continue adding `Project`-specific API tests.
    """

    client_class = EnvironmentToProjectRewriteClient

    def test_create_team(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.assertEqual(Team.objects.count(), 1)
        self.assertEqual(Project.objects.count(), 1)
        response = self.client.post("/api/projects/@current/environments/", {"name": "Test"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Team.objects.count(), 2)
        self.assertEqual(Project.objects.count(), 2)
        response_data = response.json()
        self.assertLessEqual(
            {
                "name": "Test",
                "access_control": False,
                "effective_membership_level": OrganizationMembership.Level.ADMIN,
            }.items(),
            response_data.items(),
        )
        self.assertEqual(self.organization.teams.count(), 2)

    def test_user_create_project_for_org_via_url(self):
        # Set both current and new org to high enough membership level
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        current_org, _, _ = Organization.objects.bootstrap(self.user, name="other_org")
        other_org = self.organization  # Bootstrapping above sets it to the current org
        assert Team.objects.count() == 2
        assert Project.objects.count() == 2

        assert current_org.id == self.user.current_organization_id
        response = self.client.post(f"/api/organizations/{current_org.id}/projects/", {"name": "Via current org"})
        self.assertEqual(response.status_code, 201)
        assert response.json()["organization"] == str(current_org.id)
        assert Team.objects.count() == 3
        assert Project.objects.count() == 3

        assert other_org.id != self.user.current_organization_id
        response = self.client.post(f"/api/organizations/{other_org.id}/projects/", {"name": "Via path org"})
        self.assertEqual(response.status_code, 201, msg=response.json())
        assert response.json()["organization"] == str(other_org.id)
        assert Team.objects.count() == 4
        assert Project.objects.count() == 4

    def test_user_cannot_create_project_in_org_without_access(self):
        _, _, _ = Organization.objects.bootstrap(self.user, name="other_org")
        other_org = self.organization  # Bootstrapping above sets it to the current org

        assert other_org.id != self.user.current_organization_id
        response = self.client.post(f"/api/organizations/{other_org.id}/projects/", {"name": "Via path org"})
        self.assertEqual(response.status_code, 403, msg=response.json())
        assert response.json() == self.permission_denied_response("Your organization access level is insufficient.")

    def test_user_that_does_not_belong_to_an_org_cannot_create_a_projec(self):
        user = User.objects.create(email="no_org@posthog.com")
        self.client.force_login(user)

        response = self.client.post("/api/projects/", {"name": "Test"})
        self.assertEqual(response.status_code, 404, response.content)
        self.assertEqual(
            response.json(),
            {
                "type": "invalid_request",
                "code": "not_found",
                "detail": "You need to belong to an organization.",
                "attr": None,
            },
        )

    def test_rename_project_as_org_member_allowed(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.patch(f"/api/projects/@current/", {"name": "Erinaceus europaeus"})
        self.project.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.project.name, "Erinaceus europaeus")

    def test_list_projects_restricted_ones_hidden(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        other_team = Team.objects.create(
            organization=self.organization,
            name="Other",
        )

        # Set up new access control system - restrict project to no default access
        AccessControl.objects.create(
            team=other_team,
            access_level="none",
            resource="project",
            resource_id=str(other_team.id),
        )

        # The other team should not be returned as it's restricted for the logged-in user
        projects_response = self.client.get(f"/api/environments/")

        # 9 (above):
        with self.assertNumQueries(FuzzyInt(16, 17)):
            current_org_response = self.client.get(f"/api/organizations/{self.organization.id}/")

        self.assertEqual(projects_response.status_code, 200)
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
        self.assertEqual(current_org_response.status_code, 200)
        self.assertEqual(
            current_org_response.json().get("teams"),
            [
                {
                    "id": self.team.id,
                    "uuid": str(self.team.uuid),
                    "organization": str(self.organization.id),
                    "project_id": self.team.project.id,
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

    def test_cannot_create_project_in_org_without_access(self):
        self.organization_membership.delete()

        response = self.client.post(f"/api/organizations/{self.organization.id}/projects/", {"name": "Test"})

        self.assertEqual(response.status_code, 404, response.json())
        self.assertEqual(response.json(), self.not_found_response("Organization not found."))
