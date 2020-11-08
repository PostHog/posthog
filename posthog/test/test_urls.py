from django.test import Client, TestCase

from posthog.models import Team, User, organization
from posthog.models.organization import OrganizationInvite, OrganizationMembership


class TestUrls(TestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()

    def test_logout_temporary_token_reset(self):
        # create random team
        invited_email = "jane@acme.com"
        organization, team, user = User.objects.bootstrap("test", "adminuser@posthog.com", None)
        invite = OrganizationInvite.objects.create(organization=organization, target_email=invited_email)
        # create a new user and log them in
        with self.settings(TEST=False):
            response = self.client.post(
                f"/signup/{invite.id}",
                {"name": "Jane", "email": invited_email, "password": "hunter2", "emailOptIn": "",},
                follow=True,
            )
        self.assertRedirects(response, "/")

        # fetch the user model
        user = User.objects.get(email=invited_email)
        user.temporary_token = "token123"
        user.save()

        # token still there after reload
        user = User.objects.get(id=user.id)
        self.assertEqual(user.temporary_token, "token123")

        # logout
        with self.settings(TEST=False):
            response = self.client.post("/logout", follow=True,)

            self.assertRedirects(response, "/login")

        # no more token
        user = User.objects.get(id=user.id)
        self.assertEqual(user.temporary_token, None)

    def test_signup_link_invitation(self):
        # create random team
        invited_email = "jane@acme.com"
        signup_token = "abcd1234"
        organization, team, user = User.objects.bootstrap(
            "test", "adminuser@posthog.com", None, team_fields={"signup_token": signup_token}
        )
        # create a new user and log them in
        with self.settings(TEST=False):
            response = self.client.post(
                f"/signup/{signup_token}",
                {"name": "Jane", "email": invited_email, "password": "hunter2", "emailOptIn": "",},
                follow=True,
            )
        self.assertRedirects(response, "/")
        self.assertEqual(organization.members.count(), 2)
        self.assertTrue(
            OrganizationMembership.objects.filter(organization=organization, user__email=invited_email).exists()
        )
