from posthog.models.organization import OrganizationInvite, OrganizationMembership

from .base import APIBaseTest


class TestOrganizationInvitesAPI(APIBaseTest):
    def test_add_organization_invite_email_required(self):
        response = self.client.post("/api/organizations/@current/invites/")
        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertDictEqual(
            response_data,
            {
                "type": "validation_error",
                "code": "required",
                "detail": "This field is required.",
                "attr": "target_email",
            },
        )

    def test_add_organization_invite_with_email(self):
        email = "x@x.com"
        response = self.client.post("/api/organizations/@current/invites/", {"target_email": email})
        self.assertEqual(response.status_code, 201)
        self.assertTrue(OrganizationInvite.objects.exists())
        response_data = response.json()
        response_data.pop("id")
        response_data.pop("created_at")
        response_data.pop("updated_at")
        self.assertDictEqual(
            response_data,
            {
                "target_email": email,
                "created_by_email": self.user.email,
                "created_by_id": self.user.id,
                "created_by_first_name": self.user.first_name,
            },
        )

    def test_delete_organization_invite_only_if_admin(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        invite = OrganizationInvite.objects.create(organization=self.organization)
        response = self.client.delete(f"/api/organizations/@current/invites/{invite.id}")
        self.assertEqual(
            response.data,
            {
                "type": "authentication_error",
                "code": "permission_denied",
                "detail": "Your organization access level is insufficient.",
                "attr": None,
            },
        )
        self.assertEqual(response.status_code, 403)
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        response = self.client.delete(f"/api/organizations/@current/invites/{invite.id}")
        self.assertIsNone(response.data)
        self.assertEqual(response.status_code, 204)
        self.assertFalse(OrganizationInvite.objects.exists())
