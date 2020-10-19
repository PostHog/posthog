from unittest.mock import patch

from django.test.utils import tag

from posthog.models.organization import Organization, OrganizationInvite, OrganizationMembership
from posthog.models.team import Team

from .base import APILicensedTest


class TestOrganizationEnterpriseAPI(APILicensedTest):
    def test_create_organization(self):
        response = self.client.post("/api/organizations/", {"name": "Test"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Organization.objects.count(), 2)
        response_data = response.json()
        self.assertEqual(response_data.get("name"), "Test")
        self.assertEqual(OrganizationMembership.objects.filter(organization_id=response_data.get("id")).count(), 1)
        self.assertEqual(
            OrganizationMembership.objects.get(organization_id=response_data.get("id"), user=self.user).level,
            OrganizationMembership.Level.ADMIN,
        )

    def test_delete_organization_own_second(self):
        organization, _, team = Organization.objects.bootstrap(self.user)
        self.assertTrue(Organization.objects.filter(id=organization.id).exists())
        self.assertTrue(Team.objects.filter(id=team.id).exists())
        response = self.client.delete(f"/api/organizations/{organization.id}")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Organization.objects.filter(id=organization.id).exists())
        self.assertFalse(Team.objects.filter(id=team.id).exists())

    def test_no_delete_last_organization(self):
        org_id = self.organization.id
        self.assertTrue(Organization.objects.filter(id=org_id).exists())
        response = self.client.delete(f"/api/organizations/{org_id}")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Organization.objects.filter(id=org_id).exists())

    def test_no_delete_organization_not_administrating(self):
        organization, organization_membership, team = Organization.objects.bootstrap(self.user)
        organization_membership.level = OrganizationMembership.Level.MEMBER
        organization_membership.save()
        self.assertTrue(Organization.objects.filter(id=organization.id).exists())
        self.assertTrue(Team.objects.filter(id=team.id).exists())
        response = self.client.delete(f"/api/organizations/{organization.id}")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Organization.objects.filter(id=organization.id).exists())
        self.assertTrue(Team.objects.filter(id=team.id).exists())

    def test_no_delete_organization_not_belonging_to(self):
        organization = Organization.objects.create(name="Some Other Org")
        response = self.client.delete(f"/api/organizations/{organization.id}")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Organization.objects.filter(id=organization.id).exists())
