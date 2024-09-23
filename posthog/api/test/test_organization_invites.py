import random
from unittest.mock import ANY, patch

from django.core import mail
from rest_framework import status

from ee.models.explicit_team_membership import ExplicitTeamMembership
from posthog.models.instance_setting import set_instance_setting
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.organization_invite import OrganizationInvite
from posthog.models.team.team import Team
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
                }
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
        set_instance_setting("EMAIL_HOST", "localhost")
        email = "x@x.com"

        with self.settings(EMAIL_ENABLED=True, SITE_URL="http://test.posthog.com"):
            response = self.client.post(
                "/api/organizations/@current/invites/",
                {"target_email": email},
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(OrganizationInvite.objects.exists())
        response_data = response.json()
        invite_id = response_data.pop("id")
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
                    "last_name": self.user.last_name,
                    "is_email_verified": self.user.is_email_verified,
                    "hedgehog_config": None,
                },
                "is_expired": False,
                "level": 1,
                "emailing_attempt_made": True,
                "message": None,
                "private_project_access": [],
            },
        )

        capture_props = {
            "name_provided": False,
            "current_invite_count": 1,
            "current_member_count": 1,
            "email_available": True,
            "is_bulk": False,
        }

        # Assert capture call for invitee
        mock_capture.assert_any_call(
            f"invite_{invite_id}",
            "user invited",
            properties=capture_props,
            groups={"instance": ANY, "organization": str(self.team.organization_id)},
        )

        # Assert capture call for inviting party
        mock_capture.assert_any_call(
            self.user.distinct_id,
            "team member invited",
            properties={**capture_props, "$current_url": None, "$session_id": None},
            groups={
                "instance": ANY,
                "organization": str(self.team.organization_id),
                "project": str(self.team.uuid),
            },
        )

        self.assertEqual(mock_capture.call_count, 2)

        # Assert invite email is sent
        self.assertEqual(len(mail.outbox), 1)
        self.assertListEqual(mail.outbox[0].to, [email])
        self.assertEqual(mail.outbox[0].reply_to, [self.user.email])  # Reply-To is set to the inviting user

    @patch("posthoganalytics.capture")
    def test_add_organization_invite_with_email_on_instance_but_send_email_prop_false(self, mock_capture):
        """
        Email is available on the instance, but the user creating the invite does not want to send an email to the invitee.
        """
        set_instance_setting("EMAIL_HOST", "localhost")
        email = "x@x.com"

        with self.settings(EMAIL_ENABLED=True, SITE_URL="http://test.posthog.com"):
            response = self.client.post(
                "/api/organizations/@current/invites/", {"target_email": email, "send_email": False}
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(OrganizationInvite.objects.exists())

        # Assert invite email is not sent
        self.assertEqual(len(mail.outbox), 0)

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

    def test_can_specify_membership_level_in_invite(self):
        email = "x@posthog.com"
        count = OrganizationInvite.objects.count()

        response = self.client.post(
            "/api/organizations/@current/invites/", {"target_email": email, "level": OrganizationMembership.Level.OWNER}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        obj = OrganizationInvite.objects.get(id=response.json()["id"])
        self.assertEqual(obj.level, OrganizationMembership.Level.OWNER)

        self.assertEqual(OrganizationInvite.objects.count(), count + 1)

    def test_can_specify_private_project_access_in_invite(self):
        email = "x@posthog.com"
        count = OrganizationInvite.objects.count()
        private_team = Team.objects.create(organization=self.organization, name="Private Team", access_control=True)
        ExplicitTeamMembership.objects.create(
            team=private_team,
            parent_membership=self.organization_membership,
            level=ExplicitTeamMembership.Level.ADMIN,
        )
        response = self.client.post(
            "/api/organizations/@current/invites/",
            {
                "target_email": email,
                "level": OrganizationMembership.Level.MEMBER,
                "private_project_access": [{"id": self.team.id, "level": ExplicitTeamMembership.Level.ADMIN}],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        obj = OrganizationInvite.objects.get(id=response.json()["id"])
        self.assertEqual(obj.level, OrganizationMembership.Level.MEMBER)
        self.assertEqual(
            obj.private_project_access, [{"id": self.team.id, "level": ExplicitTeamMembership.Level.ADMIN}]
        )
        self.assertEqual(OrganizationInvite.objects.count(), count + 1)

        # if member of org but admin of team, should be able to invite new project admins to private project
        org_membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        org_membership.level = OrganizationMembership.Level.MEMBER
        org_membership.save()
        email = "y@posthog.com"
        count = OrganizationInvite.objects.count()
        response = self.client.post(
            "/api/organizations/@current/invites/",
            {
                "target_email": email,
                "level": OrganizationMembership.Level.MEMBER,
                "private_project_access": [{"id": self.team.id, "level": ExplicitTeamMembership.Level.ADMIN}],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        obj = OrganizationInvite.objects.get(id=response.json()["id"])
        self.assertEqual(obj.level, OrganizationMembership.Level.MEMBER)
        self.assertEqual(
            obj.private_project_access, [{"id": self.team.id, "level": ExplicitTeamMembership.Level.ADMIN}]
        )
        self.assertEqual(OrganizationInvite.objects.count(), count + 1)

    def test_invite_fails_if_team_in_private_project_access_not_in_org(self):
        email = "x@posthog.com"
        count = OrganizationInvite.objects.count()
        other_org = Organization.objects.create(name="Other Org")
        team_in_other_org = Team.objects.create(organization=other_org, name="Private Team", access_control=True)
        response = self.client.post(
            "/api/organizations/@current/invites/",
            {
                "target_email": email,
                "level": OrganizationMembership.Level.MEMBER,
                "private_project_access": [{"id": team_in_other_org.id, "level": ExplicitTeamMembership.Level.ADMIN}],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        self.assertDictEqual(
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Team does not exist on this organization, or it is private and you do not have access to it.",
                "attr": "private_project_access",
            },
            response_data,
        )
        self.assertEqual(OrganizationInvite.objects.count(), count)

    def test_invite_fails_if_inviter_does_not_have_access_to_team(self):
        email = "xx@posthog.com"
        count = OrganizationInvite.objects.count()
        private_team = Team.objects.create(organization=self.organization, name="Private Team", access_control=True)
        response = self.client.post(
            "/api/organizations/@current/invites/",
            {
                "target_email": email,
                "level": OrganizationMembership.Level.MEMBER,
                "private_project_access": [{"id": private_team.id, "level": ExplicitTeamMembership.Level.ADMIN}],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        self.assertDictEqual(
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Team does not exist on this organization, or it is private and you do not have access to it.",
                "attr": "private_project_access",
            },
            response_data,
        )
        self.assertEqual(OrganizationInvite.objects.count(), count)

    def test_invite_fails_if_inviter_level_is_lower_than_requested_level(self):
        email = "x@posthog.com"
        count = OrganizationInvite.objects.count()
        private_team = Team.objects.create(organization=self.organization, name="Private Team", access_control=True)
        organization_membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        organization_membership.level = OrganizationMembership.Level.MEMBER
        organization_membership.save()
        ExplicitTeamMembership.objects.create(
            team=private_team,
            parent_membership=self.organization_membership,
            level=ExplicitTeamMembership.Level.MEMBER,
        )
        response = self.client.post(
            "/api/organizations/@current/invites/",
            {
                "target_email": email,
                "level": OrganizationMembership.Level.MEMBER,
                "private_project_access": [{"id": private_team.id, "level": ExplicitTeamMembership.Level.ADMIN}],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        self.assertDictEqual(
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "You cannot invite to a private project with a higher level than your own.",
                "attr": "private_project_access",
            },
            response_data,
        )
        self.assertEqual(OrganizationInvite.objects.count(), count)

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
        set_instance_setting("EMAIL_HOST", "localhost")

        count = OrganizationInvite.objects.count()
        payload = self.helper_generate_bulk_invite_payload(7)

        with self.settings(EMAIL_ENABLED=True, SITE_URL="http://test.posthog.com"):
            response = self.client.post(
                "/api/organizations/@current/invites/bulk/",
                payload,
                format="json",
                headers={"X-Posthog-Session-Id": "123", "Referer": "http://test.posthog.com/my-url"},
            )
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
        mock_capture.assert_any_call(
            self.user.distinct_id,
            "bulk invite executed",
            properties={
                "invitee_count": 7,
                "name_count": sum(1 for user in payload if user["first_name"]),
                "current_invite_count": 7,
                "current_member_count": 1,
                "email_available": True,
                "$session_id": "123",
                "$current_url": "http://test.posthog.com/my-url",
            },
            groups={
                "instance": ANY,
                "organization": str(self.team.organization_id),
                "project": str(self.team.uuid),
            },
        )

        # Assert capture call for invitee
        mock_capture.assert_any_call(
            f"invite_{OrganizationInvite.objects.last().id}",  # type: ignore
            "user invited",
            properties={
                "name_provided": True,
                "current_invite_count": 7,
                "current_member_count": 1,
                "email_available": True,
                "is_bulk": True,
            },
            groups={"instance": ANY, "organization": str(self.team.organization_id)},
        )

    def test_maximum_20_invites_per_request(self):
        count = OrganizationInvite.objects.count()
        payload = self.helper_generate_bulk_invite_payload(21)

        with self.settings(
            EMAIL_ENABLED=True,
            EMAIL_HOST="localhost",
            SITE_URL="http://test.posthog.com",
        ):
            response = self.client.post("/api/organizations/@current/invites/bulk/", payload, format="json")

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

    def test_invites_are_created_atomically(self):
        count = OrganizationInvite.objects.count()
        payload = self.helper_generate_bulk_invite_payload(5)
        payload[4]["target_email"] = None

        with self.settings(
            EMAIL_ENABLED=True,
            EMAIL_HOST="localhost",
            SITE_URL="http://test.posthog.com",
        ):
            response = self.client.post("/api/organizations/@current/invites/bulk/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # No invites created
        self.assertEqual(OrganizationInvite.objects.count(), count)

        # No emails should be sent
        self.assertEqual(len(mail.outbox), 0)

    def test_cannot_bulk_create_invites_for_another_organization(self):
        another_org = Organization.objects.create()

        count = OrganizationInvite.objects.count()
        payload = self.helper_generate_bulk_invite_payload(3)

        with self.settings(
            EMAIL_ENABLED=True,
            EMAIL_HOST="localhost",
            SITE_URL="http://test.posthog.com",
        ):
            response = self.client.post(
                f"/api/organizations/{another_org.id}/invites/bulk/",
                payload,
                format="json",
            )

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
