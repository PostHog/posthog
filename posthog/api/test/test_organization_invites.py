from typing import Optional, Type

from posthog.models import Organization
from posthog.models.organization import OrganizationInvite, OrganizationMembership
from posthog.models.user import User

from .base import TransactionBaseTest


class TestOrganizationInvitesAPI(TransactionBaseTest):
    TESTS_API = True

    def test_add_organization_invite(self):
        response = self.client.post("/api/organization/invites/")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(OrganizationInvite.objects.exists())
        response_data = response.json()
        response_data.pop("id")
        response_data.pop("created_at")
        response_data.pop("updated_at")
        self.assertDictEqual(
            response_data,
            {
                "max_uses": None,
                "uses": 0,
                "target_email": None,
                "created_by_id": self.user.id,
                "created_by_first_name": self.user.first_name,
            },
        )

    def test_add_organization_invite_with_max_uses(self):
        response = self.client.post("/api/organization/invites/", {"max_uses": 3})
        self.assertEqual(response.status_code, 201)
        self.assertTrue(OrganizationInvite.objects.exists())
        response_data = response.json()
        response_data.pop("id")
        response_data.pop("created_at")
        response_data.pop("update_at")
        self.assertDictEqual(
            response_data,
            {
                "max_uses": 3,
                "uses": 0,
                "target_email": None,
                "created_by_id": self.user.id,
                "created_by_first_name": self.user.first_name,
            },
        )

    def test_delete_organization_member(self):
        invite = OrganizationInvite.objects.create(organization=self.organization)
        response = self.client.delete(f"/api/organization/invites/{invite.id}")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(OrganizationInvite.objects.exists())
