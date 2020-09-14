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
        response_data.pop("update_at")
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

    # TDD for a /use endpoint - not in use right now, as org joining works through forms
    # def test_use_organization_invite(self):
    #     new_organization = Organization.objects.create(name="New")
    #     invite = OrganizationInvite.objects.create(organization=new_organization)
    #     self.assertFalse(OrganizationMembership.objects.filter(organization=new_organization).exists())
    #     self.assertEqual(invite.uses, 0)
    #     response = self.client.post(f"/api/organization/invites/{invite.id}/use")
    #     self.assertEqual(response.status_code, 200)
    #     invite.refresh_from_db()
    #     self.assertEqual(invite.uses, 1)
    #     self.assertTrue(OrganizationMembership.objects.filter(organization=new_organization).exists())
    #     self.assertEqual(new_organization.members.first(), self.client)

    # def test_cannot_use_organization_invite_over_maximum(self):
    #     new_organization = Organization.objects.create(name="New")
    #     invite = OrganizationInvite.objects.create(organization=new_organization, max_uses=0)
    #     self.assertFalse(OrganizationMembership.objects.filter(organization=new_organization).exists())
    #     self.assertEqual(invite.uses, 0)
    #     response = self.client.post(f"/api/organization/invites/{invite.id}/use")
    #     self.assertEqual(response.status_code, 403)
    #     invite.refresh_from_db()
    #     self.assertFalse(OrganizationMembership.objects.filter(organization=new_organization).exists())
    #     self.assertEqual(invite.uses, 0)
    #     response_data = response.json()
    #     self.assertDictEqual(
    #         response_data,
    #         {
    #             "status": 403, "detail": "This invite has been used up."
    #         }
    #     )

    # def test_cannot_use_organization_invite_if_wrong_target_email(self):
    #     new_organization = Organization.objects.create(name="New")
    #     invite = OrganizationInvite.objects.create(organization=new_organization, target_email='test@x.com')
    #     self.assertFalse(OrganizationMembership.objects.filter(organization=new_organization).exists())
    #     self.assertEqual(invite.uses, 0)
    #     response = self.client.post(f"/api/organization/invites/{invite.id}/use")
    #     self.assertEqual(response.status_code, 403)
    #     invite.refresh_from_db()
    #     self.assertFalse(OrganizationMembership.objects.filter(organization=new_organization).exists())
    #     self.assertEqual(invite.uses, 0)
    #     response_data = response.json()
    #     self.assertDictEqual(
    #         response_data,
    #         {
    #             "status": 403, "detail": "This invite is for a different email than yours."
    #         }
    #     )

    # def test_can_use_organization_invite_if_wrong_target_email(self):
    #     new_organization = Organization.objects.create(name="New")
    #     invite = OrganizationInvite.objects.create(organization=new_organization, target_email=self.user.email)
    #     self.assertFalse(OrganizationMembership.objects.filter(organization=new_organization).exists())
    #     self.assertEqual(invite.uses, 0)
    #     response = self.client.post(f"/api/organization/invites/{invite.id}/use")
    #     self.assertEqual(response.status_code, 200)
    #     invite.refresh_from_db()
    #     self.assertFalse(OrganizationMembership.objects.filter(organization=new_organization).exists())
    #     self.assertEqual(invite.uses, 1)
