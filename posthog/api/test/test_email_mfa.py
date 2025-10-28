import pytest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework import status

VALID_TEST_PASSWORD = "mighty-strong-secure-1337!!"


class TestEmailMFAAPI(APIBaseTest):
    CONFIG_AUTO_LOGIN = False

    @pytest.mark.disable_mock_email_mfa_verifier
    @patch("posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.tasks.email.send_email_mfa_link")
    @patch("posthog.helpers.two_factor_session.is_email_available", return_value=True)
    def test_login_without_totp_triggers_email_mfa(
        self, mock_is_email_available, mock_send_email, mock_feature_enabled
    ):
        response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        response_data = response.json()
        self.assertEqual(response_data["code"], "email_mfa_required")
        self.assertEqual(response_data["detail"], self.user.email)

        # Assert user is not logged in yet
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # Assert email task was called
        mock_send_email.assert_called_once()
        call_args = mock_send_email.call_args
        self.assertEqual(call_args[0][0], self.user.id)
        self.assertIsNotNone(call_args[0][1])  # Token should be present

    @pytest.mark.disable_mock_email_mfa_verifier
    @patch("posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.tasks.email.send_email_mfa_link")
    @patch("posthog.helpers.two_factor_session.is_email_available", return_value=True)
    def test_email_mfa_verification_success_and_always_remembers_device(
        self, mock_is_email_available, mock_send_email, mock_feature_enabled
    ):
        # Trigger email MFA
        self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})

        # Get the token that was generated
        token = mock_send_email.call_args[0][1]

        # Verify the token
        response = self.client.post(
            "/api/login/email-mfa/",
            {"email": self.user.email, "token": token},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"success": True})

        # Check that remember cookie was ALWAYS set (same as TOTP 2FA behavior)
        cookies = response.cookies
        remember_cookie_found = False
        for cookie_name in cookies.keys():
            if cookie_name.startswith("remember-cookie_"):
                remember_cookie_found = True
                break
        self.assertTrue(remember_cookie_found, "Remember device cookie should always be set")

        # Assert user is now logged in
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["email"], self.user.email)

        # Logout and try to login again - should NOT require email MFA (remembered for 30 days)
        self.client.post("/logout", follow=True)
        response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"success": True})

    @pytest.mark.disable_mock_email_mfa_verifier
    @patch("posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.tasks.email.send_email_mfa_link")
    @patch("posthog.helpers.two_factor_session.is_email_available", return_value=True)
    def test_email_mfa_verification_with_invalid_token(
        self, mock_is_email_available, mock_send_email, mock_feature_enabled
    ):
        # Trigger email MFA
        self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})

        # Try to verify with invalid token
        response = self.client.post(
            "/api/login/email-mfa/",
            {"email": self.user.email, "token": "invalid_token_123"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        if isinstance(response_data.get("detail"), dict):
            self.assertIn("invalid or has expired", response_data["detail"]["token"][0])
        else:
            self.assertIn("invalid or has expired", response_data["detail"])

        # Assert user is still not logged in
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @pytest.mark.disable_mock_email_mfa_verifier
    @patch("posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.tasks.email.send_email_mfa_link")
    @patch("posthog.helpers.two_factor_session.is_email_available", return_value=True)
    def test_email_mfa_token_expires_after_10_minutes(
        self, mock_is_email_available, mock_send_email, mock_feature_enabled
    ):
        with freeze_time("2023-01-01T10:00:00"):
            # Trigger email MFA
            self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
            token = mock_send_email.call_args[0][1]

        # Try to verify after 11 minutes
        with freeze_time("2023-01-01T10:11:00"):
            response = self.client.post(
                "/api/login/email-mfa/",
                {"email": self.user.email, "token": token},
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            response_data = response.json()
            # Check either nested format or flat format
            if isinstance(response_data.get("detail"), dict):
                self.assertIn("invalid or has expired", response_data["detail"]["token"][0])
            else:
                self.assertIn("invalid or has expired", response_data["detail"])

    @pytest.mark.disable_mock_email_mfa_verifier
    @patch("posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.tasks.email.send_email_mfa_link")
    @patch("posthog.helpers.two_factor_session.is_email_available", return_value=True)
    def test_email_mfa_token_invalidated_after_use(
        self, mock_is_email_available, mock_send_email, mock_feature_enabled
    ):
        # Trigger email MFA
        self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        token = mock_send_email.call_args[0][1]

        # Verify the token
        response = self.client.post(
            "/api/login/email-mfa/",
            {"email": self.user.email, "token": token},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Logout
        self.client.post("/logout", follow=True)

        # Try to reuse the same token (but should be blocked by remember cookie first)
        # Clear cookies to test token invalidation
        self.client.cookies.clear()
        response = self.client.post(
            "/api/login/email-mfa/",
            {"email": self.user.email, "token": token},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        if isinstance(response_data.get("detail"), dict):
            self.assertIn("invalid or has expired", response_data["detail"]["token"][0])
        else:
            self.assertIn("invalid or has expired", response_data["detail"])

    @pytest.mark.disable_mock_email_mfa_verifier
    @patch("posthog.tasks.email.send_email_mfa_link")
    def test_email_mfa_with_nonexistent_user(self, mock_send_email):
        # Try to verify with non-existent user
        response = self.client.post(
            "/api/login/email-mfa/",
            {"email": "nonexistent@posthog.com", "token": "some_token"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        if isinstance(response_data.get("detail"), dict):
            self.assertIn("invalid or has expired", response_data["detail"]["token"][0])
        else:
            self.assertIn("invalid or has expired", response_data["detail"])

    @pytest.mark.disable_mock_email_mfa_verifier
    @patch("posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.tasks.email.send_email_mfa_link")
    @patch("posthog.helpers.two_factor_session.is_email_available", return_value=True)
    def test_login_with_totp_does_not_trigger_email_mfa(
        self, mock_is_email_available, mock_send_email, mock_feature_enabled
    ):
        # Create TOTP device for user
        TOTPDevice.objects.create(user=self.user, name="default")

        response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})

        # Should trigger TOTP 2FA, not email MFA
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json()["code"], "2fa_required")

        # Email task should not have been called
        mock_send_email.assert_not_called()

    @pytest.mark.disable_mock_email_mfa_verifier
    @patch("posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.tasks.email.send_email_mfa_link")
    @patch("posthog.helpers.two_factor_session.is_email_available", return_value=True)
    def test_email_mfa_resend_success(
        self,
        mock_is_email_available,
        mock_send_email,
        mock_feature_enabled,
    ):
        with freeze_time("2023-01-01T10:00:00"):
            # Trigger email MFA
            self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
            self.assertEqual(mock_send_email.call_count, 1)

        # Resend after 61 seconds
        with freeze_time("2023-01-01T10:01:01"):
            response = self.client.post("/api/login/email-mfa/resend/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json(), {"success": True, "message": "Verification email sent"})

            # Assert email task was called again
            self.assertEqual(mock_send_email.call_count, 2)

    @pytest.mark.disable_mock_email_mfa_verifier
    @patch("posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.tasks.email.send_email_mfa_link")
    @patch("posthog.helpers.two_factor_session.is_email_available", return_value=True)
    def test_email_mfa_resend_throttle(self, mock_is_email_available, mock_send_email, mock_feature_enabled):
        with freeze_time("2023-01-01T10:00:00"):
            # Trigger email MFA - this counts towards the resend throttle
            self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
            self.assertEqual(mock_send_email.call_count, 1)

            # First resend immediately after should be throttled (initial send already used the 1/minute limit)
            response = self.client.post("/api/login/email-mfa/resend/")
            self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
            self.assertIn("Request was throttled", response.json()["detail"])

            # Email task should still only have been called once (resend was blocked)
            self.assertEqual(mock_send_email.call_count, 1)

        # After 61 seconds, resend should succeed
        with freeze_time("2023-01-01T10:01:01"):
            response = self.client.post("/api/login/email-mfa/resend/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(mock_send_email.call_count, 2)

    @pytest.mark.disable_mock_email_mfa_verifier
    @patch("posthog.tasks.email.send_email_mfa_link")
    def test_email_mfa_resend_without_pending_verification(self, mock_send_email):
        # Try to resend without triggering MFA first
        response = self.client.post("/api/login/email-mfa/resend/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("No pending email MFA verification found", response.json()["detail"])

        # Email task should not have been called
        mock_send_email.assert_not_called()

    @pytest.mark.disable_mock_email_mfa_verifier
    @patch("posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.tasks.email.send_email_mfa_link")
    @patch("posthog.helpers.two_factor_session.is_email_available", return_value=True)
    def test_email_mfa_skipped_during_reauth(self, mock_is_email_available, mock_send_email, mock_feature_enabled):
        # First, log in normally (triggers email MFA)
        response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        response_data = response.json()
        self.assertEqual(response_data["code"], "email_mfa_required")

        # Verify the first email was sent
        self.assertEqual(mock_send_email.call_count, 1)
        token = mock_send_email.call_args[0][1]

        # Complete the email MFA verification to log in
        response = self.client.post("/api/login/email-mfa/", {"email": self.user.email, "token": token})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # User is now logged in - verify
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # This covers the case where email MFA is enabled after users are already logged in
        session = self.client.session
        session.pop("two_factor_verified", None)
        session.save()

        # Now try to reauth while already logged in (should skip email MFA)
        response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Email should still only have been sent once (not a second time for reauth)
        self.assertEqual(mock_send_email.call_count, 1)
