from unittest.mock import patch

from django.test.utils import tag

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User

from .base import APILicensedTest


class TestTeamEnterpriseAPI(APILicensedTest):
    def test_create_team(self):
        response = self.client.post("/api/projects/", {"name": "Test"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Team.objects.count(), 2)
        response_data = response.json()
        self.assertEqual(response_data.get("name"), "Default Project")
        self.assertEqual(self.organization.teams.count(), 2)

    def test_delete_team_own_second(self):
        team = Team.objects.create(organization=self.organization)
        response = self.client.delete(f"/api/projects/{team.id}")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(Team.objects.filter(organization=self.organization).count(), 1)

    def test_no_delete_last_team(self):
        self.assertEqual(Team.objects.filter(organization=self.organization).count(), 1)
        response = self.client.delete(f"/api/projects/{self.team.id}")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Team.objects.filter(organization=self.organization).count(), 1)

    def test_no_delete_team_not_administrating_organization(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        team = Team.objects.create(organization=self.organization)
        response = self.client.delete(f"/api/projects/{team.id}")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Team.objects.filter(organization=self.organization).count(), 2)

    def test_no_delete_team_not_belonging_to_organization(self):
        team_1 = Team.objects.create()
        response = self.client.delete(f"/api/projects/{team_1.id}")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Team.objects.filter(id=team_1.id).exists())
        organization, _, _ = User.objects.bootstrap("X", "someone@x.com", "qwerty", "Someone")
        team_2 = Team.objects.create(organization=organization)
        response = self.client.delete(f"/api/projects/{team_2.id}")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Team.objects.filter(id=organization.id).count(), 2)
