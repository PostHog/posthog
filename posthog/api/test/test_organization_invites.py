import random
from unittest.mock import ANY, patch

from django.core import mail
from rest_framework import status

from posthog.models.organization import Organization, OrganizationInvite, OrganizationMembership
from posthog.test.base import APIBaseTest

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

    # Listing invites

    def test_cant_list_invites_for_an_alien_organization(self):
        org = Organization.objects.create(name="Alien Org")
        invite = OrganizationInvite.objects.create(target_email="siloed@posthog.com", organization=org)

        response = self.client.get(f"/api/organizations/{org.id}/invites/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response())

        # Even though there's no retrieve for invites, permissions are validated first
        response = self.client.get(f"/api/organizations/{org.id}/invites/{invite.id}")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response())

    # Creating invites

    @patch("posthoganalytics.capture")
    def test_add_organization_invite_email_required(self, mock_capture):
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

        mock_capture.assert_not_called()

    @patch("posthoganalytics.capture")
    def test_add_organization_invite_with_email(self, mock_capture):
        email = "x@x.com"

        with self.settings(EMAIL_ENABLED=True, EMAIL_HOST="localhost", SITE_URL="http://test.posthog.com"):
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
                    "uuid": str(self.user.uuid),
                    "distinct_id": self.user.distinct_id,
                    "email": self.user.email,
                    "first_name": self.user.first_name,
                },
                "is_expired": False,
                "emailing_attempt_made": True,
            },
        )

        # Assert capture was called
        mock_capture.assert_called_once_with(
            self.user.distinct_id,
            "team invite executed",
            properties={
                "name_provided": False,
                "current_invite_count": 1,
                "current_member_count": 1,
                "email_available": True,
            },
            groups={"instance": ANY, "organization": str(self.team.organization_id), "project": str(self.team.uuid),},
        )

        # Assert invite email is sent
        self.assertEqual(len(mail.outbox), 1)
        self.assertListEqual(mail.outbox[0].to, [email])
        self.assertEqual(mail.outbox[0].reply_to, [self.user.email])  # Reply-To is set to the inviting user

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

    def test_cannot_create_invite_for_another_org(self):
        another_org = Organization.objects.create(name="Another Org")

        count = OrganizationInvite.objects.count()
        email = "x@posthog.com"
        response = self.client.post(f"/api/organizations/{another_org.id}/invites/", {"target_email": email})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response())

        self.assertEqual(OrganizationInvite.objects.count(), count)

    # Bulk create invites

    @patch("posthoganalytics.capture")
    def test_allow_bulk_creating_invites(self, mock_capture):
        count = OrganizationInvite.objects.count()
        payload = self.helper_generate_bulk_invite_payload(7)

        with self.settings(EMAIL_ENABLED=True, EMAIL_HOST="localhost", SITE_URL="http://test.posthog.com"):
            response = self.client.post("/api/organizations/@current/invites/bulk/", payload, format="json",)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()

        self.assertEqual(OrganizationInvite.objects.count(), count + 7)

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

        # Assert capture was called
        mock_capture.assert_called_once_with(
            self.user.distinct_id,
            "bulk invite executed",
            properties={
                "invitee_count": 7,
                "name_count": sum(1 for user in payload if user["first_name"]),
                "current_invite_count": 7,
                "current_member_count": 1,
                "email_available": True,
            },
            groups={"instance": ANY, "organization": str(self.team.organization_id), "project": str(self.team.uuid),},
        )

    def test_maximum_20_invites_per_request(self):
        count = OrganizationInvite.objects.count()
        payload = self.helper_generate_bulk_invite_payload(21)

        with self.settings(EMAIL_ENABLED=True, EMAIL_HOST="localhost", SITE_URL="http://test.posthog.com"):
            response = self.client.post("/api/organizations/@current/invites/bulk/", payload, format="json",)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "max_length",
                "detail": "A maximum of 20 invites can be sent in a single request.",
                "attr": None,
            },
        )

        # No invites created
        self.assertEqual(OrganizationInvite.objects.count(), count)

        # No emails should be sent
        self.assertEqual(len(mail.outbox), 0)

    def test_invites_are_create_atomically(self):
        count = OrganizationInvite.objects.count()
        payload = self.helper_generate_bulk_invite_payload(5)
        payload[4]["target_email"] = None

        with self.settings(EMAIL_ENABLED=True, EMAIL_HOST="localhost", SITE_URL="http://test.posthog.com"):
            response = self.client.post("/api/organizations/@current/invites/bulk/", payload, format="json",)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # No invites created
        self.assertEqual(OrganizationInvite.objects.count(), count)

        # No emails should be sent
        self.assertEqual(len(mail.outbox), 0)

    def test_cannot_bulk_create_invites_for_another_organization(self):
        another_org = Organization.objects.create()

        count = OrganizationInvite.objects.count()
        payload = self.helper_generate_bulk_invite_payload(3)

        with self.settings(EMAIL_ENABLED=True, EMAIL_HOST="localhost", SITE_URL="http://test.posthog.com"):
            response = self.client.post(f"/api/organizations/{another_org.id}/invites/bulk/", payload, format="json",)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response())

        # No invites created
        self.assertEqual(OrganizationInvite.objects.count(), count)

        # No emails should be sent
        self.assertEqual(len(mail.outbox), 0)

    # Deleting invites

    def test_delete_organization_invite_if_plain_member(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        invite = OrganizationInvite.objects.create(organization=self.organization)
        response = self.client.delete(f"/api/organizations/@current/invites/{invite.id}")
        self.assertEqual(response.content, b"")  # Empty response
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(OrganizationInvite.objects.exists())
