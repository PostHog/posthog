from typing import cast
from unittest.mock import patch

from django.test.utils import tag
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

    def test_at_most_one_organization_on_noncloud(self):
        organization, _, team = Organization.objects.bootstrap(self.user, name="X")

        response = self.client.post("/api/organizations/", {"name": "Test"})
        response_data = response.json()

        self.assertTrue(Organization.objects.filter(id=organization.id).exists())
        self.assertTrue(Team.objects.filter(id=team.id).exists())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Organization.objects.count(), 1)
        self.assertDictEqual(
            response_data,
            {
                "attr": None,
                "detail": "Private instances can only have one organization! Join the existing one.",
                "code": "invalid_input",
                "type": "validation_error",
            },
        )

    def test_delete_second_managed_organization(self):
        with self.settings(MULTI_TENANCY=True):
            organization, _, team = Organization.objects.bootstrap(self.user, name="X")
            self.assertTrue(Organization.objects.filter(id=organization.id).exists())
            self.assertTrue(Team.objects.filter(id=team.id).exists())
            response = self.client.delete(f"/api/organizations/{organization.id}")
            self.assertEqual(response.status_code, 204)
            self.assertFalse(Organization.objects.filter(id=organization.id).exists())
            self.assertFalse(Team.objects.filter(id=team.id).exists())

    def test_no_delete_last_organization(self):
        self.bootstrap()
        org_id = self.organization.id
        self.assertTrue(Organization.objects.filter(id=org_id).exists())
        response = self.client.delete(f"/api/organizations/{org_id}")
        self.assertEqual(
            response.data,
            {
                "attr": None,
                "detail": f"Cannot remove organization since that would leave member {self.CONFIG_USER_EMAIL} organization-less, which is not supported yet.",
                "code": "invalid_input",
                "type": "validation_error",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Organization.objects.filter(id=org_id).exists())

    def test_no_delete_organization_not_administrating(self):
        organization, organization_membership, team = Organization.objects.bootstrap(self.user)
        organization_membership = cast(OrganizationMembership, organization_membership)
        organization_membership.level = OrganizationMembership.Level.MEMBER
        organization_membership.save()
        self.assertTrue(Organization.objects.filter(id=organization.id).exists())
        self.assertTrue(Team.objects.filter(id=team.id).exists())
        response = self.client.delete(f"/api/organizations/{organization.id}")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Organization.objects.filter(id=organization.id).exists())
        self.assertTrue(Team.objects.filter(id=team.id).exists())

    def test_no_delete_organization_not_belonging_to(self):
        self.bootstrap()
        # as member only
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        with self.settings(MUTLI_TENANCY=True):  # avoiding 1 org per instance limit
            organization = Organization.objects.create(name="Some Other Org")
        response_1 = self.client.delete(f"/api/organizations/{organization.id}")
        self.assertEqual(
            response_1.data, {"attr": None, "detail": "Not found.", "code": "not_found", "type": "invalid_request"}
        )
        self.assertEqual(response_1.status_code, 404)
        self.assertTrue(Organization.objects.filter(id=organization.id).exists())
        # as admin
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response_2 = self.client.delete(f"/api/organizations/{organization.id}")
        self.assertEqual(
            response_2.data, {"attr": None, "detail": "Not found.", "code": "not_found", "type": "invalid_request"}
        )
        self.assertEqual(response_2.status_code, 404)
        self.assertTrue(Organization.objects.filter(id=organization.id).exists())
