from django.test import Client, TestCase

from posthog.models import Team, User


class TestUrls(TestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()

    def test_logout_temporary_token_reset(self):
        # create random team
        team = Team.objects.create_with_data(
            name="test", users=[User.objects.create_user(email="adminuser@posthog.com")]
        )

        # create a new user and log them in
        with self.settings(TEST=False):
            response = self.client.post(
                "/signup/{}".format(team.signup_token),
                {"name": "Jane", "email": "jane@acme.com", "password": "hunter2", "emailOptIn": "",},
                follow=True,
            )
        self.assertRedirects(response, "/")

        # fetch the user model
        user = User.objects.get(email="jane@acme.com")
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
