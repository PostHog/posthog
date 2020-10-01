from posthog.models.organization import OrganizationInvite

from .base import APIBaseTest


class TestOrganizationInvitesAPI(APIBaseTest):
    def test_add_organization_invite(self):
        response = self.client.post("/api/organizations/@current/invites/")
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
                "created_by_email": self.user.email,
                "created_by_id": self.user.id,
                "created_by_first_name": self.user.first_name,
            },
        )

    def test_add_organization_invite_with_max_uses(self):
        response = self.client.post("/api/organizations/@current/invites/", {"max_uses": 3})
        self.assertEqual(response.status_code, 201)
        self.assertTrue(OrganizationInvite.objects.exists())
        response_data = response.json()
        response_data.pop("id")
        response_data.pop("created_at")
        response_data.pop("updated_at")
        self.assertDictEqual(
            response_data,
            {
                "max_uses": 3,
                "uses": 0,
                "target_email": None,
                "created_by_id": self.user.id,
                "created_by_email": self.user.email,
                "created_by_first_name": self.user.first_name,
            },
        )

    def test_delete_organization_member(self):
        invite = OrganizationInvite.objects.create(organization=self.organization)
        response = self.client.delete(f"/api/organizations/@current/invites/{invite.id}")
        self.assertIsNone(response.data)
        self.assertEqual(response.status_code, 204)
        self.assertFalse(OrganizationInvite.objects.exists())
