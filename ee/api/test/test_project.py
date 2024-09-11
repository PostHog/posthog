from ee.api.test.test_team import team_enterprise_api_test_factory
from posthog.api.test.test_team import EnvironmentToProjectRewriteClient
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.project import Project
from posthog.models.team.team import Team


class TestProjectEnterpriseAPI(team_enterprise_api_test_factory()):
    """
    We inherit from TestTeamEnterpriseAPI, as previously /api/projects/ referred to the Team model, which used to mean "project".
    Now as Team means "environment" and Project is separate, we must ensure backward compatibility of /api/projects/.
    At the same time, this class is where we can continue adding `Project`-specific API tests.
    """

    client_class = EnvironmentToProjectRewriteClient

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
