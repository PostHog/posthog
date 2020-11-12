from unittest.mock import patch

from posthog.models import Team, User

from .base import BaseTest


class TestUser(BaseTest):
    TESTS_API = True

    def test_redirect_to_site(self):
        self.team.app_urls = ["http://somewebsite.com"]
        self.team.save()
        response = self.client.get("/api/user/redirect_to_site/?actionId=1")
        self.assertIn("http://somewebsite.com", response.url)

    def test_create_user_with_distinct_id(self):
        with self.settings(TEST=False):
            user = User.objects.create_user(first_name="Tim", email="tim@gmail.com", password=None)
        self.assertNotEqual(user.distinct_id, "")
        self.assertNotEqual(user.distinct_id, None)

    def test_user_team_update(self):
        response = self.client.patch(
            "/api/user/",
            data={"team": {"opt_out_capture": True, "anonymize_ips": False, "session_recording_opt_in": True}},
            content_type="application/json",
        ).json()

        self.assertEqual(response["team"]["opt_out_capture"], True)
        self.assertEqual(response["team"]["anonymize_ips"], False)
        self.assertEqual(response["team"]["session_recording_opt_in"], True)

        team = Team.objects.get(id=self.team.id)
        self.assertEqual(team.opt_out_capture, True)
        self.assertEqual(team.anonymize_ips, False)
        self.assertEqual(team.session_recording_opt_in, True)


class TestUserChangePassword(BaseTest):
    TESTS_API = True
    ENDPOINT: str = "/api/user/change_password/"

    def send_request(self, payload):
        return self.client.patch(self.ENDPOINT, payload, content_type="application/json")

    def test_change_password_no_data(self):
        response = self.send_request({})
        self.assertEqual(response.status_code, 400)

    def test_change_password_invalid_old_password(self):
        response = self.send_request({"oldPassword": "12345", "newPassword": "12345"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Incorrect old password")

    def test_change_password_invalid_new_password(self):
        response = self.send_request({"oldPassword": self.TESTS_PASSWORD, "newPassword": "123456"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "This password is too short. It must contain at least 8 characters.")

    def test_change_password_success(self):
        response = self.send_request({"oldPassword": self.TESTS_PASSWORD, "newPassword": "prettyhardpassword123456",})
        self.assertEqual(response.status_code, 200)


class TestUserSlackWebhook(BaseTest):
    TESTS_API = True
    ENDPOINT: str = "/api/user/test_slack_webhook/"

    def send_request(self, payload):
        return self.client.post(self.ENDPOINT, payload, content_type="application/json")

    def test_slack_webhook_no_webhook(self):
        response = self.send_request({})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["error"], "no webhook URL")

    def test_slack_webhook_bad_url(self):
        response = self.send_request({"webhook": "blabla"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["error"], "invalid webhook URL")

    def test_slack_webhook_bad_url_full(self):
        response = self.send_request({"webhook": "http://localhost/bla"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["error"], "invalid webhook URL")


class TestLoginViews(BaseTest):
    def test_redirect_to_preflight_when_no_users(self):
        User.objects.all().delete()
        response = self.client.get("/", follow=True)
        self.assertRedirects(response, "/preflight")
