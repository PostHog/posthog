import random

from django.core import mail
from rest_framework import status

from posthog.models.organization import OrganizationInvite, OrganizationMembership

from .base import APIBaseTest

NAME_SEEDS = ["John", "Jane", "Alice", "Bob", ""]


class TestOrganizationInvitesAPI(APIBaseTest):
    def helper_generate_bulk_invite_payload(self, count: int):

        payload = []

        for i in range(0, count):
            payload.append(
                {
                    "target_email": f"test+{random.randint(1000000, 9999999)}@posthog.com",
                    "first_name": NAME_SEEDS[i % len(NAME_SEEDS)],
                },
            )

        return payload

    # Creating invites

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
                "first_name": "",
                "created_by": {
                    "id": self.user.id,
                    "distinct_id": self.user.distinct_id,
                    "email": self.user.email,
                    "first_name": self.user.first_name,
                },
                "is_expired": False,
                "emailing_attempt_made": False,
            },
        )

    def test_can_create_invites_for_the_same_email_multiple_times(self):
        email = "x@posthog.com"
        count = OrganizationInvite.objects.count()

        for _ in range(0, 2):
            response = self.client.post("/api/organizations/@current/invites/", {"target_email": email})
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            obj = OrganizationInvite.objects.get(id=response.json()["id"])
            self.assertEqual(obj.target_email, email)
            self.assertEqual(obj.created_by, self.user)

        self.assertEqual(OrganizationInvite.objects.count(), count + 2)

    # Bulk create invites

    def test_allow_bulk_creating_invites(self):
        count = OrganizationInvite.objects.count()
        payload = self.helper_generate_bulk_invite_payload(7)

        with self.settings(EMAIL_ENABLED=True, EMAIL_HOST="localhost", SITE_URL="http://test.posthog.com"):
            response = self.client.post(
                "/api/organizations/@current/invites/bulk/", {"invites": payload}, format="json",
            )

        self.assertEqual(OrganizationInvite.objects.count(), count + 7)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()["invites"]

        self.assertEqual(len(response_data), 7)

        # Check objects are properly saved and response matches
        for i, item in enumerate(response_data):
            instance = OrganizationInvite.objects.get(id=item["id"])
            self.assertEqual(instance.target_email, payload[i]["target_email"])
            self.assertEqual(instance.target_email, item["target_email"])
            self.assertEqual(instance.first_name, payload[i]["first_name"])
            self.assertEqual(instance.first_name, item["first_name"])

        # Emails should be sent
        self.assertEqual(len(mail.outbox), 7)

    def test_maximum_20_invites_per_request(self):
        pass

    def test_invites_are_create_atomically(self):
        pass

    def test_only_admin_or_owner_can_bulk_create_invites(self):
        pass

    # Deleting invites

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
