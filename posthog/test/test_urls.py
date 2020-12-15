from django.test import Client, TestCase
from rest_framework import status

from posthog.models import OrganizationInvite, OrganizationMembership, User
from posthog.test.base import BaseTest


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

    def test_invitation_signup_token(self):
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
                {"name": "Jane", "email": invited_email, "password": "hunter2", "emailOptIn": ""},
                follow=True,
            )
        self.assertRedirects(response, "/")
        self.assertEqual(organization.members.count(), 2)
        self.assertTrue(
            OrganizationMembership.objects.filter(organization=organization, user__email=invited_email).exists()
        )

    def test_logged_out_user_is_redirected_to_login(self):
        self.client.logout()

        response = self.client.get(
            '/insights?interval=day&display=ActionsLineGraph&events=[{"id":"$pageview","name":"$pageview","type":"events","order":0}]&properties=[]',
        )

        # Test that the URL is properly encoded to redirect the user to the final destination
        self.assertRedirects(
            response,
            "/login?next=/insights%3Finterval%3Dday%26display%3DActionsLineGraph%26events%3D%5B%257B%2522id%2522%3A%2522%24pageview%2522%2C%2522name%2522%3A%2522%24pageview%2522%2C%2522type%2522%3A%2522events%2522%2C%2522order%2522%3A0%257D%5D%26properties%3D%5B%5D",
            fetch_redirect_response=False,
        )

    def test_login_with_next_url(self):
        organization, team, user = User.objects.bootstrap(
            "test", "adminuser@posthog.com", None, team_fields={"signup_token": "abcd1234"}
        )
        User.objects.create_and_join(organization=organization, email="jane@acme.com", password="password")

        # Standard redirect
        response = self.client.post("/login?next=/demo", {"email": "jane@acme.com", "password": "password"})
        self.assertRedirects(response, "/demo")

        # Complex redirect (url-encoded)
        self.client.logout()
        response = self.client.post(
            "/login?next=/insights%3Finterval%3Dday%26display%3DActionsLineGraph%26events%3D%5B%257B%2522id%2522%3A%2522%24pageview%2522%2C%2522name%2522%3A%2522%24pageview%2522%2C%2522type%2522%3A%2522events%2522%2C%2522order%2522%3A0%257D%5D%26properties%3D%5B%5D",
            {"email": "jane@acme.com", "password": "password"},
        )
        self.assertRedirects(
            response,
            '/insights?interval=day&display=ActionsLineGraph&events=[{"id":"$pageview","name":"$pageview","type":"events","order":0}]&properties=[]',
        )


class TestUrlsLoggedIn(BaseTest):
    TESTS_API = True

    def test_invitation_join(self):
        organization, team, user = User.objects.bootstrap("test", "adminuser@posthog.com", None)
        invite = OrganizationInvite.objects.create(
            organization=organization, target_email=self.TESTS_EMAIL, created_by=user
        )
        with self.settings(TEST=False):
            response = self.client.post(f"/signup/{invite.id}", follow=True,)
        self.assertRedirects(response, "/")
        self.assertEqual(organization.members.count(), 2)
        self.assertTrue(OrganizationMembership.objects.filter(organization=organization, user=self.user).exists())
