from unittest.mock import patch

from posthog.models import Team, User

from .base import APIBaseTest, BaseTest


class TestUser(BaseTest):
    TESTS_API = True

    def test_redirect_to_site(self):
        self.team.app_urls = ["http://somewebsite.com"]
        self.team.save()
        response = self.client.get("/api/users/@me/redirect_to_site/?actionId=1")
        self.assertIn("http://somewebsite.com", response.url)

    def test_create_user_with_distinct_id(self):
        with self.settings(TEST=False):
            user = User.objects.create_user(name="Tim", email="tim@gmail.com", password=None)
        self.assertNotEqual(user.distinct_id, "")
        self.assertNotEqual(user.distinct_id, None)


class TestUserChangePassword(BaseTest):
    TESTS_API = True
    ENDPOINT: str = "/api/users/@me/change_password/"

    def send_request(self, payload):
        return self.client.patch(self.ENDPOINT, payload, content_type="application/json")

    def test_change_password_no_data(self):
        response = self.send_request({})
        self.assertEqual(response.status_code, 400)

    def test_change_password_invalid_current_password(self):
        response = self.send_request(
            {"current_password": "12345", "new_password": "12345", "new_password_repeat": "12345"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "detail": "Incorrect current password!",
                "attr": None,
                "code": "invalid_input",
                "type": "validation_error",
            },
        )

    def test_change_password_invalid_new_password(self):
        with self.settings(DEBUG=1):
            response = self.send_request(
                {"current_password": self.TESTS_PASSWORD, "new_password": "123456", "new_password_repeat": "123456"}
            )
        self.assertEqual(
            response.json(), {"message": "This password is too short. It must contain at least 8 characters."}
        )
        self.assertEqual(response.status_code, 400)

    def test_change_password_requires_repeat(self):
        response = self.send_request(
            {"current_password": self.TESTS_PASSWORD, "new_password": "prettyhardpassword123456",}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "attr": None,
                "code": "invalid_input",
                "detail": "New password and repeated new password don't match!",
                "type": "validation_error",
            },
        )

    def test_change_password_success(self):
        response = self.send_request(
            {
                "current_password": self.TESTS_PASSWORD,
                "new_password": "prettyhardpassword123456",
                "new_password_repeat": "prettyhardpassword123456",
            }
        )
        self.assertEqual(response.status_code, 200)


class TestLoginViews(BaseTest):
    def test_redirect_to_preflight_when_no_users(self):
        User.objects.all().delete()
        response = self.client.get("/", follow=True)
        self.assertRedirects(response, "/preflight")
