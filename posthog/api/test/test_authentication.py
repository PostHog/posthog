from datetime import UTC, timedelta, datetime
from typing import cast
import uuid
from unittest.mock import ANY, patch

from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.utils import timezone
from django_otp.oath import totp
from django_otp.util import random_hex
from freezegun import freeze_time
from rest_framework import status
from social_django.models import UserSocialAuth
from two_factor.utils import totp_digits
import time

from posthog.api.authentication import password_reset_token_generator
from posthog.models import User
from posthog.models.instance_setting import set_instance_setting
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal
from posthog.test.base import APIBaseTest
from django_otp.plugins.otp_static.models import StaticDevice
from posthog.auth import OAuthAccessTokenAuthentication, ProjectSecretAPIKeyAuthentication, ProjectSecretAPIKeyUser
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from rest_framework.parsers import JSONParser


VALID_TEST_PASSWORD = "mighty-strong-secure-1337!!"


def totp_str(key):
    return str(totp(key)).zfill(totp_digits())


class TestLoginPrecheckAPI(APIBaseTest):
    """
    Tests the login precheck API.
    Please note additional login tests are included in ee/api/test/test_authentication.py
    """

    CONFIG_AUTO_LOGIN = False

    def test_login_precheck_with_unenforced_sso(self):
        OrganizationDomain.objects.create(
            domain="witw.app",
            organization=self.organization,
            verified_at=timezone.now(),
        )

        response = self.client.post("/api/login/precheck", {"email": "any_user_name_here@witw.app"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"sso_enforcement": None, "saml_available": False})

    def test_login_precheck_with_sso_enforced_with_invalid_license(self):
        # Note no Enterprise license can be found
        OrganizationDomain.objects.create(
            domain="witw.app",
            organization=self.organization,
            verified_at=timezone.now(),
            sso_enforcement="google-oauth2",
        )
        User.objects.create_and_join(self.organization, "spain@witw.app", self.CONFIG_PASSWORD)

        response = self.client.post("/api/login/precheck", {"email": "spain@witw.app"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"sso_enforcement": None, "saml_available": False})


class TestLoginAPI(APIBaseTest):
    """
    Tests the general password login API.
    Please note additional login tests are included in ee/api/test/test_authentication.py (e.g. testing SSO enforcement)
    """

    CONFIG_AUTO_LOGIN = False

    @patch("posthog.tasks.user_identify.identify_task")
    @patch("posthoganalytics.capture")
    def test_user_logs_in_with_email_and_password(self, mock_capture, mock_identify):
        self.user.is_email_verified = True
        self.user.save()
        response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"success": True})

        # Test that we're actually logged in
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["email"], self.user.email)

        # Assert the event was captured.
        mock_capture.assert_called_once_with(
            self.user.distinct_id,
            "user logged in",
            properties={"social_provider": ""},
            groups={
                "instance": ANY,
                "organization": str(self.team.organization_id),
                "project": str(self.team.uuid),
            },
        )

    @patch("posthog.api.authentication.is_email_available", return_value=True)
    @patch("posthog.api.authentication.EmailVerifier.create_token_and_send_email_verification")
    def test_email_unverified_user_cant_log_in_if_email_available(
        self, mock_send_email_verification, mock_is_email_available
    ):
        self.user.is_email_verified = False
        self.user.save()
        self.assertEqual(self.user.is_email_verified, False)
        response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Test that we're not logged in
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        mock_is_email_available.assert_called_once()

        # Assert the email was sent.
        mock_send_email_verification.assert_called_once_with(self.user)

    @patch("posthog.api.authentication.is_email_available", return_value=True)
    @patch("posthog.api.authentication.EmailVerifier.create_token_and_send_email_verification")
    @patch("posthog.api.authentication.is_email_verification_disabled", return_value=True)
    def test_email_unverified_user_can_log_in_if_email_available_but_verification_disabled_flag_is_true(
        self, mock_is_verification_disabled, mock_send_email_verification, mock_is_email_available
    ):
        self.user.is_email_verified = False
        self.user.save()
        self.assertEqual(self.user.is_email_verified, False)
        response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"success": True})

        # Test that we're actually logged in
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["email"], self.user.email)

        mock_is_verification_disabled.assert_called_once()
        mock_is_email_available.assert_called_once()
        mock_send_email_verification.assert_not_called()

    @patch("posthog.api.authentication.is_email_available", return_value=True)
    @patch("posthog.api.authentication.EmailVerifier.create_token_and_send_email_verification")
    def test_email_unverified_null_user_can_log_in_if_email_available(
        self, mock_send_email_verification, mock_is_email_available
    ):
        """When email verification was added, existing users were set to is_email_verified=null.
        If someone is null they should still be allowed to log in until we explicitly decide to lock them out."""
        self.assertEqual(self.user.is_email_verified, None)
        response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Test that we are logged in
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_is_email_available.assert_called_once()
        # Assert the email was sent.
        mock_send_email_verification.assert_called_once_with(self.user)

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
        response = self.client.post(
            "/api/login",
            {"email": "user2@posthog.com", "password": self.CONFIG_PASSWORD},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json(), self.ERROR_INVALID_CREDENTIALS)

        # Assert user is not logged in
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertNotIn("email", response.json())

        # Events never get reported
        mock_capture.assert_not_called()

    def test_cant_login_without_required_attributes(self):
        required_attributes = ["email", "password"]

        for attribute in required_attributes:
            body = {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD}
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
                response = self.client.post(
                    "/api/login",
                    {"email": "new_user@posthog.com", "password": "invalid"},
                )
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
                    "detail": "Too many failed login attempts. Please try again in 10 minutes.",
                    "attr": None,
                },
            )


class TestTwoFactorAPI(APIBaseTest):
    """
    Tests the two factor view set.
    """

    CONFIG_AUTO_LOGIN = False

    def test_login_2fa_enabled(self):
        device = self.user.totpdevice_set.create(name="default", key=random_hex(), digits=6)  # type: ignore

        response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(
            response.json(),
            {
                "type": "server_error",
                "code": "2fa_required",
                "detail": "2FA is required.",
                "attr": None,
            },
        )

        # Assert user is not logged in
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertNotIn("email", response.json())

        response = self.client.post("/api/login/token", {"token": totp_str(device.bin_key)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["email"], self.user.email)

        # Test remembering cookie
        self.client.post("/logout", follow=True)
        response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_2fa_expired(self):
        self.user.totpdevice_set.create(name="default", key=random_hex(), digits=6)  # type: ignore

        with freeze_time("2023-01-01T10:00:00"):
            response = self.client.post(
                "/api/login",
                {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD},
            )
            assert response.status_code == status.HTTP_401_UNAUTHORIZED, response.json()
            self.assertEqual(
                response.json(),
                {
                    "type": "server_error",
                    "code": "2fa_required",
                    "detail": "2FA is required.",
                    "attr": None,
                },
            )

        with freeze_time("2023-01-01T10:30:00"):
            response = self.client.post("/api/login/token", {"token": "abcdefg"})
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(
                response.json(),
                {
                    "type": "validation_error",
                    "code": "2fa_expired",
                    "detail": "Login attempt has expired. Re-enter username/password.",
                    "attr": None,
                },
            )

        response = self.client.get("/api/users/@me/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED, response.json()

    def test_2fa_throttling(self):
        self.user.totpdevice_set.create(name="default", key=random_hex(), digits=6)  # type: ignore
        self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(
            self.client.post("/api/login/token", {"token": "abcdefg"}).json()["code"],
            "2fa_invalid",
        )
        self.assertEqual(
            self.client.post("/api/login/token", {"token": "abcdefg"}).json()["code"],
            "2fa_too_many_attempts",
        )

    @patch("posthog.api.authentication.send_two_factor_auth_backup_code_used_email")
    def test_login_with_backup_code(self, mock_send_email):
        """Test that a user can log in using a backup code instead of TOTP"""
        self.user.totpdevice_set.create(name="default", key=random_hex(), digits=6)  # type: ignore
        static_device = StaticDevice.objects.create(user=self.user, name="backup")
        static_device.token_set.create(token="123456")

        # First authenticate with username/password
        response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json()["code"], "2fa_required")

        # Then authenticate with backup code
        response = self.client.post("/api/login/token", {"token": "123456"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify we're logged in
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["email"], self.user.email)

        # Verify the backup code was consumed (can't be reused)
        self.assertFalse(static_device.token_set.filter(token="123456").exists())

        # Verify email was triggered
        mock_send_email.delay.assert_called_once_with(self.user.id)

    @patch("posthog.api.authentication.send_two_factor_auth_backup_code_used_email")
    def test_backup_code_is_consumed_after_use(self, mock_send_email):
        """Test that backup codes are one-time use only"""
        self.user.totpdevice_set.create(name="default", key=random_hex(), digits=6)  # type: ignore
        static_device = StaticDevice.objects.create(user=self.user, name="backup")
        static_device.token_set.create(token="123456")

        # First authenticate with username/password
        self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})

        # Use backup code once
        response = self.client.post("/api/login/token", {"token": "123456"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify email was triggered
        mock_send_email.delay.assert_called_once_with(self.user.id)

        # Log out
        self.client.logout()

        # Wait for throttling to expire
        time.sleep(2)

        # Try to authenticate again with same backup code
        self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        response = self.client.post("/api/login/token", {"token": "123456"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], "2fa_invalid")

    @patch("posthog.api.authentication.send_two_factor_auth_backup_code_used_email")
    def test_backup_codes_work_when_totp_device_is_throttled(self, mock_send_email):
        """Test that backup codes still work even if TOTP device is throttled"""
        self.user.totpdevice_set.create(name="default", key=random_hex(), digits=6)  # type: ignore
        static_device = StaticDevice.objects.create(user=self.user, name="backup")
        static_device.token_set.create(token="123456")

        # First authenticate with username/password
        self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})

        # Trigger TOTP throttling with invalid attempts
        self.client.post("/api/login/token", {"token": "000000"})
        self.client.post("/api/login/token", {"token": "000000"})

        # Wait for throttling to expire
        import time

        time.sleep(2)

        # Backup code should still work
        response = self.client.post("/api/login/token", {"token": "123456"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify email was triggered
        mock_send_email.delay.assert_called_once_with(self.user.id)


class TestPasswordResetAPI(APIBaseTest):
    CONFIG_AUTO_LOGIN = False

    def setUp(self):
        # prevent throttling of user requests to pass on from one test
        # to the next
        cache.clear()
        return super().setUp()

    # Password reset request

    @freeze_time("2021-10-05T12:00:00")
    @patch("posthoganalytics.capture")
    def test_anonymous_user_can_request_password_reset(self, mock_capture):
        set_instance_setting("EMAIL_HOST", "localhost")

        with self.settings(CELERY_TASK_ALWAYS_EAGER=True, SITE_URL="https://my.posthog.net"):
            response = self.client.post("/api/reset/", {"email": self.CONFIG_EMAIL})
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(response.content.decode(), "")
        self.assertEqual(response.headers["Content-Length"], "0")

        user: User = User.objects.get(email=self.CONFIG_EMAIL)
        self.assertEqual(
            user.requested_password_reset_at,
            datetime(2021, 10, 5, 12, 0, 0, tzinfo=UTC),
        )

        self.assertSetEqual({",".join(outmail.to) for outmail in mail.outbox}, {self.CONFIG_EMAIL})

        self.assertEqual(mail.outbox[0].subject, "Reset your PostHog password")
        self.assertEqual(mail.outbox[0].body, "")  # no plain-text version support yet

        html_message = mail.outbox[0].alternatives[0][0]  # type: ignore
        self.validate_basic_html(
            html_message,
            "https://my.posthog.net",
            preheader="Please follow the link inside to reset your password.",
        )

        # validate reset token
        link_index = html_message.find("https://my.posthog.net/reset")
        reset_link = html_message[link_index : html_message.find('"', link_index)]
        self.assertTrue(
            password_reset_token_generator.check_token(
                self.user,
                reset_link.replace("https://my.posthog.net/reset/", "").replace(f"{self.user.uuid}/", ""),
            )
        )

    def test_reset_with_sso_available(self):
        """
        If the user has logged in / signed up with SSO, we let them know so they don't have to reset their password.
        """
        set_instance_setting("EMAIL_HOST", "localhost")

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

        with self.settings(CELERY_TASK_ALWAYS_EAGER=True, SITE_URL="https://my.posthog.net"):
            response = self.client.post("/api/reset/", {"email": self.CONFIG_EMAIL})
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.assertSetEqual({",".join(outmail.to) for outmail in mail.outbox}, {self.CONFIG_EMAIL})

        html_message = mail.outbox[0].alternatives[0][0]  # type: ignore
        self.validate_basic_html(
            html_message,
            "https://my.posthog.net",
            preheader="Please follow the link inside to reset your password.",
        )

        # validate reset token
        link_index = html_message.find("https://my.posthog.net/reset")
        reset_link = html_message[link_index : html_message.find('"', link_index)]
        self.assertTrue(
            password_reset_token_generator.check_token(
                self.user,
                reset_link.replace(f"https://my.posthog.net/reset/{self.user.uuid}/", ""),
            )
        )

        # check we mention SSO providers
        self.assertIn("Google, GitHub", html_message)
        self.assertIn("https://my.posthog.net/login", html_message)  # CTA link

    def test_success_response_even_on_invalid_email(self):
        set_instance_setting("EMAIL_HOST", "localhost")

        with self.settings(CELERY_TASK_ALWAYS_EAGER=True, SITE_URL="https://my.posthog.net"):
            response = self.client.post("/api/reset/", {"email": "i_dont_exist@posthog.com"})
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # No emails should be sent
        self.assertEqual(len(mail.outbox), 0)

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

    def test_cant_reset_more_than_six_times(self):
        set_instance_setting("EMAIL_HOST", "localhost")

        for i in range(7):
            with self.settings(CELERY_TASK_ALWAYS_EAGER=True, SITE_URL="https://my.posthog.net"):
                response = self.client.post("/api/reset/", {"email": self.CONFIG_EMAIL})
            if i < 6:
                self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
            else:
                # Fourth request should fail
                self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
                self.assertDictContainsSubset(
                    {"attr": None, "code": "throttled", "type": "throttled_error"},
                    response.json(),
                )

        # Three emails should be sent, fourth should not
        self.assertEqual(len(mail.outbox), 6)

    def test_is_rate_limited_on_email_not_ip(self):
        set_instance_setting("EMAIL_HOST", "localhost")

        for email in ["email@posthog.com", "other-email@posthog.com"]:
            for i in range(7):
                with self.settings(CELERY_TASK_ALWAYS_EAGER=True, SITE_URL="https://my.posthog.net"):
                    response = self.client.post("/api/reset/", {"email": email})
                if i < 6:
                    self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
                else:
                    # Fourth request should fail
                    self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
                    self.assertDictContainsSubset(
                        {"attr": None, "code": "throttled", "type": "throttled_error"},
                        response.json(),
                    )

    # Token validation

    def test_can_validate_token(self):
        token = password_reset_token_generator.make_token(self.user)
        response = self.client.get(f"/api/reset/{self.user.uuid}/?token={token}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(response.content.decode(), "")
        self.assertEqual(response.headers["Content-Length"], "0")

    def test_cant_validate_token_without_a_token(self):
        response = self.client.get(f"/api/reset/{self.user.uuid}/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "required",
                "detail": "This field is required.",
                "attr": "token",
            },
        )

    def test_invalid_token_returns_error(self):
        valid_token = password_reset_token_generator.make_token(self.user)

        with freeze_time(timezone.now() - timedelta(seconds=86_401)):
            # tokens expire after one day
            expired_token = password_reset_token_generator.make_token(self.user)

        for token in [
            valid_token[:-1],
            "not_even_trying",
            self.user.uuid,
            expired_token,
        ]:
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

    @patch("posthog.tasks.user_identify.identify_task")
    @patch("posthoganalytics.capture")
    def test_user_can_reset_password(self, mock_capture, mock_identify):
        self.client.logout()  # extra precaution to test login

        self.user.requested_password_reset_at = datetime.now()
        self.user.save()
        token = password_reset_token_generator.make_token(self.user)
        response = self.client.post(f"/api/reset/{self.user.uuid}/", {"token": token, "password": VALID_TEST_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(response.content.decode(), "")

        # assert the user gets logged in automatically
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["email"], self.CONFIG_EMAIL)

        # check password was changed
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(VALID_TEST_PASSWORD))
        self.assertFalse(self.user.check_password(self.CONFIG_PASSWORD))  # type: ignore
        self.assertEqual(self.user.requested_password_reset_at, None)

        # old password is gone
        self.client.logout()
        response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # new password can be used immediately
        response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": VALID_TEST_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # assert events were captured
        mock_capture.assert_any_call(
            self.user.distinct_id,
            "user logged in",
            properties={"social_provider": ""},
            groups={
                "instance": ANY,
                "organization": str(self.team.organization_id),
                "project": str(self.team.uuid),
            },
        )
        mock_capture.assert_any_call(
            self.user.distinct_id,
            "user password reset",
            groups={
                "instance": ANY,
                "organization": str(self.team.organization_id),
                "project": str(self.team.uuid),
            },
        )
        self.assertEqual(mock_capture.call_count, 2)

    def test_cant_set_short_password(self):
        token = password_reset_token_generator.make_token(self.user)
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
            {
                "type": "validation_error",
                "code": "required",
                "detail": "This field is required.",
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

    def test_cant_reset_password_with_invalid_token(self):
        valid_token = password_reset_token_generator.make_token(self.user)

        with freeze_time(timezone.now() - timedelta(seconds=86_401)):
            # tokens expire after one day
            expired_token = password_reset_token_generator.make_token(self.user)

        for token in [
            valid_token[:-1],
            "not_even_trying",
            self.user.uuid,
            expired_token,
        ]:
            response = self.client.post(
                f"/api/reset/{self.user.uuid}/",
                {"token": token, "password": "a12345678"},
            )
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
        token = password_reset_token_generator.make_token(self.user)

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
                "/api/reset/e2e_test_user/",
                {"token": "e2e_test_token", "password": "a12345678"},
            )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)


class TestPersonalAPIKeyAuthentication(APIBaseTest):
    def test_personal_api_key_updates_last_used_at_hourly(self):
        self.client.logout()

        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="X",
            user=self.user,
            last_used_at="2021-08-25T21:09:14",
            secure_value=hash_key_value(personal_api_key),
        )

        with freeze_time("2021-08-25T22:10:14.252"):
            response = self.client.get(
                f"/api/projects/{self.team.pk}/feature_flags/",
                HTTP_AUTHORIZATION=f"Bearer {personal_api_key}",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)

            model_key = PersonalAPIKey.objects.get(secure_value=hash_key_value(personal_api_key))

            self.assertEqual(str(model_key.last_used_at), "2021-08-25 22:10:14.252000+00:00")

    def test_personal_api_key_updates_last_used_at_outside_the_year(self):
        self.client.logout()

        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="X",
            user=self.user,
            last_used_at="2021-08-25T21:09:14",
            secure_value=hash_key_value(personal_api_key),
        )

        with freeze_time("2022-08-25T22:00:14.252"):
            response = self.client.get(
                f"/api/projects/{self.team.pk}/feature_flags/",
                HTTP_AUTHORIZATION=f"Bearer {personal_api_key}",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)

            model_key = PersonalAPIKey.objects.get(secure_value=hash_key_value(personal_api_key))

            self.assertEqual(str(model_key.last_used_at), "2022-08-25 22:00:14.252000+00:00")

    def test_personal_api_key_updates_last_used_at_outside_the_day(self):
        self.client.logout()

        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="X",
            user=self.user,
            last_used_at="2021-08-25T21:09:14",
            secure_value=hash_key_value(personal_api_key),
        )

        with freeze_time("2021-08-26T22:00:14.252"):
            response = self.client.get(
                f"/api/projects/{self.team.pk}/feature_flags/",
                HTTP_AUTHORIZATION=f"Bearer {personal_api_key}",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)

            model_key = PersonalAPIKey.objects.get(secure_value=hash_key_value(personal_api_key))

            self.assertEqual(str(model_key.last_used_at), "2021-08-26 22:00:14.252000+00:00")

    def test_personal_api_key_updates_last_used_when_none(self):
        self.client.logout()

        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="X", user=self.user, secure_value=hash_key_value(personal_api_key))

        with freeze_time("2022-08-25T22:00:14.252"):
            response = self.client.get(
                f"/api/projects/{self.team.pk}/feature_flags/",
                HTTP_AUTHORIZATION=f"Bearer {personal_api_key}",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)

            model_key = PersonalAPIKey.objects.get(secure_value=hash_key_value(personal_api_key))

            self.assertEqual(str(model_key.last_used_at), "2022-08-25 22:00:14.252000+00:00")

    def test_personal_api_key_does_not_update_last_used_at_within_the_hour(self):
        self.client.logout()

        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="X",
            user=self.user,
            last_used_at="2021-08-25T21:09:14",
            secure_value=hash_key_value(personal_api_key),
        )

        with freeze_time("2021-08-25T21:14:14.252"):
            response = self.client.get(
                f"/api/projects/{self.team.pk}/feature_flags/",
                HTTP_AUTHORIZATION=f"Bearer {personal_api_key}",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)

            model_key = PersonalAPIKey.objects.get(secure_value=hash_key_value(personal_api_key))
            self.assertEqual(str(model_key.last_used_at), "2021-08-25 21:09:14+00:00")

    def test_personal_api_key_does_not_update_last_used_at_when_in_the_past(self):
        self.client.logout()

        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="X",
            user=self.user,
            last_used_at="2021-08-25T21:09:14",
            secure_value=hash_key_value(personal_api_key),
        )

        with freeze_time("2021-08-24T21:14:14.252"):
            response = self.client.get(
                f"/api/projects/{self.team.pk}/feature_flags/",
                HTTP_AUTHORIZATION=f"Bearer {personal_api_key}",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)

            model_key = PersonalAPIKey.objects.get(secure_value=hash_key_value(personal_api_key))
            self.assertEqual(str(model_key.last_used_at), "2021-08-25 21:09:14+00:00")


class TestTimeSensitivePermissions(APIBaseTest):
    def test_after_timeout_modifications_require_reauthentication(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        now = datetime.now()
        with freeze_time(now):
            res = self.client.patch("/api/organizations/@current", {"name": "new name"})
            assert res.status_code == 200

        with freeze_time(now + timedelta(seconds=settings.SESSION_SENSITIVE_ACTIONS_AGE - 100)):
            res = self.client.patch("/api/organizations/@current", {"name": "new name"})
            assert res.status_code == 200

        with freeze_time(now + timedelta(seconds=settings.SESSION_SENSITIVE_ACTIONS_AGE + 10)):
            res = self.client.patch("/api/organizations/@current", {"name": "new name"})
            assert res.status_code == 403
            assert res.json() == {
                "type": "authentication_error",
                "code": "permission_denied",
                "detail": "This action requires you to be recently authenticated.",
                "attr": None,
            }

            res = self.client.get("/api/organizations/@current")
            assert res.status_code == 200


class TestProjectSecretAPIKeyAuthentication(APIBaseTest):
    def setUp(self):
        super().setUp()  # Call the setup from APIBaseTest
        self.team.secret_api_token = "phs_JVRb8fNi0XyIKGgUCyi29ZJUOXEr6NF2dKBy5Ws8XVeF11C"
        self.team.save()
        self.factory = APIRequestFactory()  # Use APIRequestFactory instead of RequestFactory

    def test_authenticate_with_valid_secret_api_key_in_header(self):
        # Simulate a request with a valid secret API key
        wsgi_request = self.factory.get(
            "/",
            data=None,
            secure=False,
            headers={"AUTHORIZATION": f"Bearer {self.team.secret_api_token}"},
        )
        request = Request(wsgi_request)  # Wrap the WSGIRequest in a DRF Request

        authenticator = ProjectSecretAPIKeyAuthentication()
        result = authenticator.authenticate(request)
        assert result is not None
        user, _ = result

        self.assertIsNotNone(user)
        self.assertIsInstance(user, ProjectSecretAPIKeyUser)
        self.assertEqual(user.team, self.team)

    def test_authenticate_with_valid_secret_api_key_in_body(self):
        # Simulate a request with a valid secret API key
        wsgi_request = self.factory.post(
            "/",
            data=f'{{"secret_api_key": "{self.team.secret_api_token}"}}',
            content_type="application/json",
        )
        request = Request(wsgi_request)  # Wrap the WSGIRequest in a DRF Request
        request.parsers = [JSONParser()]  # Explicitly set JSONParser

        authenticator = ProjectSecretAPIKeyAuthentication()
        result = authenticator.authenticate(request)
        assert result is not None
        user, _ = result

        self.assertIsNotNone(user)
        self.assertIsInstance(user, ProjectSecretAPIKeyUser)
        self.assertEqual(user.team, self.team)

    def test_authenticate_with_valid_secret_api_key_in_query_string(self):
        # Simulate a request with a valid secret API key
        wsgi_request = self.factory.get(f"/?secret_api_key={self.team.secret_api_token}")
        request = Request(wsgi_request)  # Wrap the WSGIRequest in a DRF Request

        authenticator = ProjectSecretAPIKeyAuthentication()
        result = authenticator.authenticate(request)
        assert result is not None
        user, _ = result

        self.assertIsNotNone(user)
        self.assertIsInstance(user, ProjectSecretAPIKeyUser)
        self.assertEqual(user.team, self.team)

    def test_authenticate_with_invalid_secret_api_key(self):
        # Simulate a request with an invalid secret API key
        wsgi_request = self.factory.get("/", HTTP_AUTHORIZATION="Bearer phs_NOT_A_VALID_KEY")
        request = Request(wsgi_request)  # Wrap the WSGIRequest in a DRF Request

        authenticator = ProjectSecretAPIKeyAuthentication()
        result = authenticator.authenticate(request)

        self.assertIsNone(result)

    def test_authenticate_without_secret_api_key(self):
        # Simulate a request without a secret API key
        wsgi_request = self.factory.get("/")
        request = Request(wsgi_request)  # Wrap the WSGIRequest in a DRF Request

        authenticator = ProjectSecretAPIKeyAuthentication()
        result = authenticator.authenticate(request)

        self.assertIsNone(result)


class TestOAuthAccessTokenAuthentication(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()

        self.oauth_app = OAuthApplication.objects.create(
            name="Test App",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            skip_authorization=False,
            organization=self.organization,
            user=self.user,
        )

        self.access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.oauth_app,
            token="test_access_token_123",
            expires=timezone.now() + timedelta(hours=1),
            scope="openid profile",
        )

    def test_authenticate_with_valid_oauth_token(self):
        wsgi_request = self.factory.get(
            "/",
            headers={"AUTHORIZATION": f"Bearer {self.access_token.token}"},
        )
        request = Request(wsgi_request)

        authenticator = OAuthAccessTokenAuthentication()
        result = authenticator.authenticate(request)

        self.assertIsNotNone(result)
        user, _ = cast(tuple[User, None], result)

        self.assertEqual(user, self.user)
        self.assertIsNone(_)

    def test_authenticate_with_invalid_oauth_token(self):
        wsgi_request = self.factory.get(
            "/",
            headers={"AUTHORIZATION": "Bearer invalid_token_123"},
        )
        request = Request(wsgi_request)

        authenticator = OAuthAccessTokenAuthentication()
        result = authenticator.authenticate(request)

        # Should return None for nonexistent tokens to allow next auth method
        self.assertIsNone(result)

    def test_authenticate_with_expired_oauth_token(self):
        expired_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.oauth_app,
            token="expired_token_123",
            expires=timezone.now() - timedelta(hours=1),
            scope="openid profile",
        )

        wsgi_request = self.factory.get(
            "/",
            headers={"AUTHORIZATION": f"Bearer {expired_token.token}"},
        )
        request = Request(wsgi_request)

        authenticator = OAuthAccessTokenAuthentication()

        with self.assertRaises(Exception) as context:
            authenticator.authenticate(request)

        self.assertIn("Access token has expired", str(context.exception))

    def test_authenticate_with_inactive_user(self):
        self.user.is_active = False
        self.user.save()

        wsgi_request = self.factory.get(
            "/",
            headers={"AUTHORIZATION": f"Bearer {self.access_token.token}"},
        )
        request = Request(wsgi_request)

        authenticator = OAuthAccessTokenAuthentication()

        with self.assertRaises(Exception) as context:
            authenticator.authenticate(request)

        self.assertIn("User associated with access token is disabled", str(context.exception))

    def test_authenticate_without_bearer_token(self):
        wsgi_request = self.factory.get("/")
        request = Request(wsgi_request)

        authenticator = OAuthAccessTokenAuthentication()
        result = authenticator.authenticate(request)

        self.assertIsNone(result)

    @patch("posthog.auth.tag_queries")
    def test_authenticate_tags_queries_correctly(self, mock_tag_queries):
        wsgi_request = self.factory.get(
            "/",
            headers={"AUTHORIZATION": f"Bearer {self.access_token.token}"},
        )
        request = Request(wsgi_request)

        authenticator = OAuthAccessTokenAuthentication()
        result = authenticator.authenticate(request)

        self.assertIsNotNone(result)

        mock_tag_queries.assert_called_once_with(
            user_id=self.user.pk,
            team_id=self.team.pk,
            access_method="oauth",
        )

    def test_authenticate_header_returns_correct_value(self):
        wsgi_request = self.factory.get("/")
        request = Request(wsgi_request)

        authenticator = OAuthAccessTokenAuthentication()
        header = authenticator.authenticate_header(request)

        self.assertEqual(header, "Bearer")

    def test_authenticate_with_nonexistent_token_returns_none_for_next_auth_method(self):
        """Test that when a token doesn't exist in the database, the method returns None
        to allow the next authentication method to have a go."""
        wsgi_request = self.factory.get(
            "/",
            headers={"AUTHORIZATION": "Bearer nonexistent_token_123"},
        )
        request = Request(wsgi_request)

        authenticator = OAuthAccessTokenAuthentication()
        result = authenticator.authenticate(request)

        # Should return None, not raise an exception
        self.assertIsNone(result)

    def test_authenticate_with_token_validation_error_raises_exception(self):
        """Test that when there's an error during token validation (not just token not found),
        an AuthenticationFailed exception is raised."""
        # Create a token without an associated application
        invalid_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=None,  # This will cause a validation error
            token="invalid_app_token_123",
            expires=timezone.now() + timedelta(hours=1),
            scope="openid profile",
        )

        wsgi_request = self.factory.get(
            "/",
            headers={"AUTHORIZATION": f"Bearer {invalid_token.token}"},
        )
        request = Request(wsgi_request)

        authenticator = OAuthAccessTokenAuthentication()

        with self.assertRaises(Exception) as context:
            authenticator.authenticate(request)

        self.assertIn("Access token is not associated with a valid application", str(context.exception))

    def test_authenticate_with_user_not_found_raises_exception(self):
        """Test that when the user associated with the token is not found,
        an AuthenticationFailed exception is raised."""
        # Create a token without a user
        token_without_user = OAuthAccessToken.objects.create(
            user=None,
            application=self.oauth_app,
            token="no_user_token_123",
            expires=timezone.now() + timedelta(hours=1),
            scope="openid profile",
        )

        wsgi_request = self.factory.get(
            "/",
            headers={"AUTHORIZATION": f"Bearer {token_without_user.token}"},
        )
        request = Request(wsgi_request)

        authenticator = OAuthAccessTokenAuthentication()

        with self.assertRaises(Exception) as context:
            authenticator.authenticate(request)

        self.assertIn("User associated with access token not found", str(context.exception))

    def test_oauth_access_token_user_properties_are_accessible(self):
        """Test that user.id and user.current_team_id are accessible for tag_queries."""
        # Test that the user has the required properties
        self.assertIsNotNone(self.access_token.user.id)
        self.assertIsInstance(self.access_token.user.id, int)
        self.assertEqual(self.access_token.user.id, self.user.pk)

        # Test that current_team_id is accessible
        self.assertIsNotNone(self.access_token.user.current_team_id)
        self.assertIsInstance(self.access_token.user.current_team_id, int)
        self.assertEqual(self.access_token.user.current_team_id, self.team.pk)

    def test_oauth_access_token_calls_tag_queries_with_correct_parameters(self):
        """Test that tag_queries is called with the correct user_id and team_id."""
        with patch("posthog.auth.tag_queries") as mock_tag_queries:
            wsgi_request = self.factory.get(
                "/",
                headers={"AUTHORIZATION": f"Bearer {self.access_token.token}"},
            )
            request = Request(wsgi_request)

            authenticator = OAuthAccessTokenAuthentication()
            result = authenticator.authenticate(request)

            self.assertIsNotNone(result)
            self.assertIsInstance(self.user.pk, int)
            self.assertIsInstance(self.user.current_team_id, int)

            # Verify tag_queries was called with correct parameters
            mock_tag_queries.assert_called_once_with(
                user_id=self.user.pk,
                team_id=self.user.current_team_id,
                access_method="oauth",
            )
