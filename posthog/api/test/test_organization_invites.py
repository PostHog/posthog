from rest_framework import status

from posthog.models.organization import OrganizationInvite, OrganizationMembership

from .base import APIBaseTest


class TestOrganizationInvitesAPI(APIBaseTest):
    def test_add_organization_invite_email_required(self):
        response = self.client.post("/api/organizations/@current/invites/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
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
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
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
                "is_expired": False,
                "emailing_attempt_made": False,
            },
        )

    def test_can_create_invites_for_the_same_email_multiple_times(self):
        email = "x@x.com"
        count = OrganizationInvite.objects.count()

        for _ in range(0, 2):
            response = self.client.post("/api/organizations/@current/invites/", {"target_email": email})
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            obj = OrganizationInvite.objects.get(id=response.json()["id"])
            self.assertEqual(obj.target_email, email)
            self.assertEqual(obj.created_by, self.user)

        self.assertEqual(OrganizationInvite.objects.count(), count + 2)

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
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        response = self.client.delete(f"/api/organizations/@current/invites/{invite.id}")
        self.assertIsNone(response.data)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(OrganizationInvite.objects.exists())
