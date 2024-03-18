from unittest.mock import ANY, patch

from django.utils import timezone
from django_otp.oath import totp
from django_otp.util import random_hex
from freezegun import freeze_time
from rest_framework import status
from two_factor.utils import totp_digits

from posthog.models import User
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal
from posthog.test.base import APIBaseTest


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
