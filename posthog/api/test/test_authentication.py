import datetime
import uuid
from unittest.mock import patch

import pytest
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.utils import timezone
from freezegun import freeze_time
from rest_framework import status
from social_django.models import UserSocialAuth

from posthog.models import User
from posthog.test.base import APIBaseTest


class TestAuthenticationAPI(APIBaseTest):
    CONFIG_AUTO_LOGIN = False

    @patch("posthoganalytics.capture")
    def test_user_logs_in_with_email_and_password(self, mock_capture):
        response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"success": True})

        # Test that we're actually logged in
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["email"], self.user.email)

        # Assert the event was captured.
        mock_capture.assert_called_once_with(
            self.user.distinct_id, "user logged in", properties={"social_provider": ""}
        )

    @patch("posthoganalytics.capture")
    def test_user_cant_login_with_incorrect_password(self, mock_capture):

        invalid_passwords = ["1234", "abcdefgh", "testpassword1234", "😈😈😈"]

        for password in invalid_passwords:
            response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": password})
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.json(), self.ERROR_INVALID_CREDENTIALS)

            # Assert user is not logged in
            response = self.client.get("/api/users/@me/")
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
            self.assertNotIn("email", response.json())

        # Events never get reported
        mock_capture.assert_not_called()

    @patch("posthoganalytics.capture")
    def test_user_cant_login_with_incorrect_email(self, mock_capture):

        response = self.client.post("/api/login", {"email": "user2@posthog.com", "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json(), self.ERROR_INVALID_CREDENTIALS)

        # Assert user is not logged in
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertNotIn("email", response.json())

        # Events never get reported
        mock_capture.assert_not_called()

    def test_cant_login_without_required_attributes(self):
        required_attributes = [
            "email",
            "password",
        ]

        for attribute in required_attributes:
            body = {
                "email": self.CONFIG_EMAIL,
                "password": self.CONFIG_PASSWORD,
            }
            body.pop(attribute)

            response = self.client.post("/api/login/", body)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(
                response.json(),
                {
                    "type": "validation_error",
                    "code": "required",
                    "detail": "This field is required.",
                    "attr": attribute,
                },
            )

            # Assert user is not logged in
            response = self.client.get("/api/users/@me/")
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_endpoint_is_protected_against_brute_force_attempts(self):
        User.objects.create(email="new_user@posthog.com", password="87654321")

        # Fill the attempt limit
        with self.settings(AXES_ENABLED=True, AXES_FAILURE_LIMIT=3):
            for _ in range(0, 2):
                response = self.client.post("/api/login", {"email": "new_user@posthog.com", "password": "invalid"})
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.json(), self.ERROR_INVALID_CREDENTIALS)

                # Assert user is not logged in
                response = self.client.get("/api/users/@me/")
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

            response = self.client.post("/api/login", {"email": "new_user@posthog.com", "password": "invalid"})
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertEqual(
                response.json(),
                {
                    "type": "authentication_error",
                    "code": "too_many_failed_attempts",
                    "detail": "Too many failed login attempts. Please try again in 15 minutes.",
                    "attr": None,
                },
            )


class TestPasswordResetAPI(APIBaseTest):
    CONFIG_AUTO_LOGIN = False

    # Password reset request

    @patch("posthoganalytics.capture")
    def test_anonymous_user_can_request_password_reset(self, mock_capture):
        with self.settings(
            CELERY_TASK_ALWAYS_EAGER=True, EMAIL_HOST="localhost", SITE_URL="https://my.posthog.net",
        ):
            response = self.client.post("/api/reset/", {"email": self.CONFIG_EMAIL})
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(response.content.decode(), "")

        self.assertSetEqual({",".join(outmail.to) for outmail in mail.outbox}, set([self.CONFIG_EMAIL]))

        self.assertEqual(
            mail.outbox[0].subject, "Reset your PostHog password",
        )
        self.assertEqual(
            mail.outbox[0].body, "",
        )  # no plain-text version support yet

        html_message = mail.outbox[0].alternatives[0][0]  # type: ignore
        self.validate_basic_html(
            html_message, "https://my.posthog.net", preheader="Please follow the link inside to reset your password.",
        )

        # validate reset token
        link_index = html_message.find("https://my.posthog.net/reset")
        reset_link = html_message[link_index : html_message.find('"', link_index)]
        self.assertTrue(
            default_token_generator.check_token(
                self.user, reset_link.replace("https://my.posthog.net/reset/", "").replace(f"{self.user.uuid}/", "")
            )
        )

    def test_reset_with_sso_available(self):
        """
        If the user has logged in / signed up with SSO, we let them know so they don't have to reset their password.
        """
        UserSocialAuth.objects.create(
            user=self.user,
            provider="google-oauth2",
            extra_data='"{"expires": 3599, "auth_time": 1633412833, "token_type": "Bearer", "access_token": "ya29"}"',
        )

        UserSocialAuth.objects.create(
            user=self.user,
            provider="github",
            extra_data='"{"expires": 3599, "auth_time": 1633412833, "token_type": "Bearer", "access_token": "ya29"}"',
        )

        with self.settings(
            CELERY_TASK_ALWAYS_EAGER=True, EMAIL_HOST="localhost", SITE_URL="https://my.posthog.net",
        ):
            response = self.client.post("/api/reset/", {"email": self.CONFIG_EMAIL})
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.assertSetEqual({",".join(outmail.to) for outmail in mail.outbox}, set([self.CONFIG_EMAIL]))

        html_message = mail.outbox[0].alternatives[0][0]  # type: ignore
        self.validate_basic_html(
            html_message, "https://my.posthog.net", preheader="Please follow the link inside to reset your password.",
        )

        # validate reset token
        link_index = html_message.find("https://my.posthog.net/reset")
        reset_link = html_message[link_index : html_message.find('"', link_index)]
        self.assertTrue(
            default_token_generator.check_token(
                self.user, reset_link.replace(f"https://my.posthog.net/reset/{self.user.uuid}/", "")
            )
        )

        # check we mention SSO providers
        self.assertIn("Google, GitHub", html_message)
        self.assertIn("https://my.posthog.net/login", html_message)  # CTA link

    def test_success_response_even_on_invalid_email(self):
        with self.settings(
            CELERY_TASK_ALWAYS_EAGER=True, EMAIL_HOST="localhost", SITE_URL="https://my.posthog.net",
        ):
            response = self.client.post("/api/reset/", {"email": "i_dont_exist@posthog.com"})
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # No emails should be sent
        self.assertEqual(len(mail.outbox), 0)

    @pytest.mark.ee
    def test_cant_reset_with_saml_enforced(self):
        with self.settings(
            CELERY_TASK_ALWAYS_EAGER=True,
            EMAIL_HOST="localhost",
            SITE_URL="https://my.posthog.net",
            SAML_ENTITY_ID="entityID",
            SAML_ACS_URL="https://saml.posthog.com",
            SAML_X509_CERT="certificate",
            SAML_ENFORCED=True,
        ):
            response = self.client.post("/api/reset/", {"email": "i_dont_exist@posthog.com"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "saml_enforced",
                "detail": "Password reset is disabled because SAML login is enforced.",
                "attr": None,
            },
        )

    def test_cant_reset_if_email_is_not_configured(self):
        with self.settings(CELERY_TASK_ALWAYS_EAGER=True):
            response = self.client.post("/api/reset/", {"email": "i_dont_exist@posthog.com"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "email_not_available",
                "detail": "Cannot reset passwords because email is not configured for your instance. Please contact your administrator.",
                "attr": None,
            },
        )

    # Token validation

    def test_can_validate_token(self):
        token = default_token_generator.make_token(self.user)
        response = self.client.get(f"/api/reset/{self.user.uuid}/?token={token}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(response.content.decode(), "")

    def test_cant_validate_token_without_a_token(self):
        response = self.client.get(f"/api/reset/{self.user.uuid}/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {"type": "validation_error", "code": "required", "detail": "This field is required.", "attr": "token"},
        )

    def test_invalid_token_returns_error(self):
        valid_token = default_token_generator.make_token(self.user)

        with freeze_time(timezone.now() - datetime.timedelta(seconds=86_401)):
            # tokens expire after one day
            expired_token = default_token_generator.make_token(self.user)

        for token in [valid_token[:-1], "not_even_trying", self.user.uuid, expired_token]:
            response = self.client.get(f"/api/reset/{self.user.uuid}/?token={token}")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(
                response.json(),
                {
                    "type": "validation_error",
                    "code": "invalid_token",
                    "detail": "This reset token is invalid or has expired.",
                    "attr": "token",
                },
            )

    # Password reset completion

    @patch("posthoganalytics.capture")
    def test_user_can_reset_password(self, mock_capture):
        self.client.logout()  # extra precaution to test login

        token = default_token_generator.make_token(self.user)
        response = self.client.post(f"/api/reset/{self.user.uuid}/", {"token": token, "password": "00112233"})
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(response.content.decode(), "")

        # assert the user gets logged in automatically
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["email"], self.CONFIG_EMAIL)

        # check password was changed
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("00112233"))
        self.assertFalse(self.user.check_password(self.CONFIG_PASSWORD))  # type: ignore

        # old password is gone
        self.client.logout()
        response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # new password can be used immediately
        response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": "00112233"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # assert events were captured
        mock_capture.assert_any_call(self.user.distinct_id, "user logged in", properties={"social_provider": ""})
        mock_capture.assert_any_call(self.user.distinct_id, "user password reset")
        self.assertEqual(mock_capture.call_count, 2)

    def test_cant_set_short_password(self):
        token = default_token_generator.make_token(self.user)
        response = self.client.post(f"/api/reset/{self.user.uuid}/", {"token": token, "password": "123"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "This password is too short. It must contain at least 8 characters.",
                "attr": "password",
            },
        )

        # user remains logged out
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # password was not changed
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.CONFIG_PASSWORD))  # type: ignore
        self.assertFalse(self.user.check_password("123"))

    def test_cant_reset_password_with_no_token(self):
        response = self.client.post(f"/api/reset/{self.user.uuid}/", {"password": "a12345678"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {"type": "validation_error", "code": "required", "detail": "This field is required.", "attr": "token",},
        )

        # user remains logged out
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # password was not changed
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.CONFIG_PASSWORD))  # type: ignore
        self.assertFalse(self.user.check_password("a12345678"))

    def test_cant_reset_password_with_invalid_token(self):
        valid_token = default_token_generator.make_token(self.user)

        with freeze_time(timezone.now() - datetime.timedelta(seconds=86_401)):
            # tokens expire after one day
            expired_token = default_token_generator.make_token(self.user)

        for token in [valid_token[:-1], "not_even_trying", self.user.uuid, expired_token]:

            response = self.client.post(f"/api/reset/{self.user.uuid}/", {"token": token, "password": "a12345678"})
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(
                response.json(),
                {
                    "type": "validation_error",
                    "code": "invalid_token",
                    "detail": "This reset token is invalid or has expired.",
                    "attr": "token",
                },
            )

            # user remains logged out
            response = self.client.get("/api/users/@me/")
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

            # password was not changed
            self.user.refresh_from_db()
            self.assertTrue(self.user.check_password(self.CONFIG_PASSWORD))  # type: ignore
            self.assertFalse(self.user.check_password("a12345678"))

    def test_cant_reset_password_with_invalid_user_id(self):
        token = default_token_generator.make_token(self.user)

        response = self.client.post(f"/api/reset/{uuid.uuid4()}/", {"token": token, "password": "a12345678"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_token",
                "detail": "This reset token is invalid or has expired.",
                "attr": "token",
            },
        )

        # user remains logged out
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # password was not changed
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.CONFIG_PASSWORD))  # type: ignore
        self.assertFalse(self.user.check_password("a12345678"))

    def test_e2e_test_special_handlers(self):
        with self.settings(E2E_TESTING=True):
            response = self.client.get("/api/reset/e2e_test_user/?token=e2e_test_token")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        with self.settings(E2E_TESTING=True):
            response = self.client.post(
                "/api/reset/e2e_test_user/", {"token": "e2e_test_token", "password": "a12345678"}
            )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
