from rest_framework import status

from ee.api.test.base import APILicensedTest
from ee.models.explicit_team_membership import ExplicitTeamMembership
from posthog.models import OrganizationMembership
from posthog.models.dashboard import Dashboard


class TestDashboardEnterpriseAPI(APILicensedTest):
    def setUp(self):
        super().setUp()
        self.team.access_control = True
        self.team.save()

    def test_retrieve_dashboard_forbidden_for_project_outsider(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        dashboard = Dashboard.objects.create(
            team=self.team, name="private dashboard", created_by=self.user, tags=["deprecated"]
        )
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_retrieve_dashboard_forbidden_for_org_admin(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        dashboard = Dashboard.objects.create(
            team=self.team, name="private dashboard", created_by=self.user, tags=["deprecated"]
        )
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_retrieve_dashboard_allowed_for_project_member(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        ExplicitTeamMembership.objects.create(team=self.team, parent_membership=self.organization_membership)
        dashboard = Dashboard.objects.create(
            team=self.team, name="private dashboard", created_by=self.user, tags=["deprecated"]
        )
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_shared_dashboard_in_private_project(self):
        self.client.logout()
        Dashboard.objects.create(
            team=self.team, share_token="testtoken", name="public dashboard", is_shared=True,
        )
        response = self.client.get("/shared_dashboard/testtoken")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
