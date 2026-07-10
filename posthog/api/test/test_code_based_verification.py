from contextlib import contextmanager

import pytest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework import status

from posthog.helpers.email_utils import ESPSuppressionResult
from posthog.helpers.two_factor_session import CODE_MAX_ATTEMPTS

VERIFY_URL = "/api/login/code-based-verification/"
RESEND_URL = "/api/login/code-based-verification/resend/"


def mock_esp_not_suppressed(*args, **kwargs):
    return ESPSuppressionResult(is_suppressed=False, from_cache=False)


@contextmanager
def enable_code_sending():
    """Force the code path on (bypass the dev/ESP/email-availability short-circuits) and capture the sent code."""
    with (
        patch("posthog.helpers.two_factor_session.check_esp_suppression", side_effect=mock_esp_not_suppressed),
        patch("posthog.helpers.two_factor_session.is_email_available", return_value=True),
        patch("posthog.helpers.two_factor_session.is_http_email_service_available", return_value=True),
        patch("posthog.tasks.email.send_code_based_verification") as mock_send,
    ):
        yield mock_send


class TestCodeBasedVerificationAPI(APIBaseTest):
    CONFIG_AUTO_LOGIN = False

    def _trigger(self, mock_send) -> str:
        """Log in with password to trigger the code, returning the 6-digit code that was emailed."""
        response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json()["code"], "code_based_verification_required")
        return mock_send.call_args[0][1]

    @pytest.mark.disable_mock_code_based_verifier
    def test_login_without_totp_emails_a_six_digit_code_and_does_not_log_in(self):
        with enable_code_sending() as mock_send:
            code = self._trigger(mock_send)

        self.assertEqual(mock_send.call_args[0][0], self.user.id)
        self.assertRegex(code, r"^\d{6}$")
        # Not logged in until the code is verified.
        self.assertEqual(self.client.get("/api/users/@me/").status_code, status.HTTP_401_UNAUTHORIZED)

    @pytest.mark.disable_mock_code_based_verifier
    def test_correct_code_logs_in_and_remembers_device(self):
        with enable_code_sending() as mock_send:
            code = self._trigger(mock_send)
            response = self.client.post(VERIFY_URL, {"code": code})
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json(), {"success": True})
            self.assertTrue(any(name.startswith("remember-cookie_") for name in response.cookies))

            self.assertEqual(self.client.get("/api/users/@me/").status_code, status.HTTP_200_OK)

            # Remembered device skips the code on the next login.
            self.client.post("/logout")
            response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
            self.assertEqual(response.status_code, status.HTTP_200_OK)

    @pytest.mark.disable_mock_code_based_verifier
    def test_wrong_code_is_rejected_but_correct_code_still_works(self):
        with enable_code_sending() as mock_send:
            code = self._trigger(mock_send)
            wrong = "000000" if code != "000000" else "111111"

            response = self.client.post(VERIFY_URL, {"code": wrong})
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.json()["code"], "invalid_code")
            self.assertEqual(self.client.get("/api/users/@me/").status_code, status.HTTP_401_UNAUTHORIZED)

            # A subsequent correct code (still under the attempt cap) succeeds.
            self.assertEqual(self.client.post(VERIFY_URL, {"code": code}).status_code, status.HTTP_200_OK)

    @pytest.mark.disable_mock_code_based_verifier
    def test_locks_out_after_max_attempts_even_with_correct_code(self):
        with enable_code_sending() as mock_send:
            code = self._trigger(mock_send)
            wrong = "000000" if code != "000000" else "111111"

            for _ in range(CODE_MAX_ATTEMPTS):
                self.assertEqual(self.client.post(VERIFY_URL, {"code": wrong}).status_code, status.HTTP_400_BAD_REQUEST)

            # The cap is now hit: even the correct code is refused and the pending state is cleared.
            response = self.client.post(VERIFY_URL, {"code": code})
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.json()["code"], "too_many_attempts")

    @pytest.mark.disable_mock_code_based_verifier
    def test_expired_code_is_rejected(self):
        with freeze_time("2024-01-01T10:00:00") as frozen, enable_code_sending() as mock_send:
            code = self._trigger(mock_send)
            frozen.move_to("2024-01-01T10:10:01")  # > 10 minute TTL
            response = self.client.post(VERIFY_URL, {"code": code})
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.json()["code"], "invalid_code")

    @pytest.mark.disable_mock_code_based_verifier
    def test_verify_without_pending_login_is_rejected(self):
        response = self.client.post(VERIFY_URL, {"code": "123456"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], "no_pending_verification")

    @pytest.mark.disable_mock_code_based_verifier
    def test_totp_user_gets_2fa_not_code_based_verification(self):
        TOTPDevice.objects.create(user=self.user, name="default")
        with enable_code_sending() as mock_send:
            response = self.client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD})
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
            self.assertEqual(response.json()["code"], "2fa_required")
            mock_send.assert_not_called()

    @pytest.mark.disable_mock_code_based_verifier
    def test_resend_issues_a_fresh_code_and_invalidates_the_previous_one(self):
        with freeze_time("2024-01-01T10:00:00") as frozen, enable_code_sending() as mock_send:
            first_code = self._trigger(mock_send)
            frozen.move_to("2024-01-01T10:01:01")  # past the 1/min resend throttle
            self.assertEqual(self.client.post(RESEND_URL).status_code, status.HTTP_200_OK)
            second_code = mock_send.call_args[0][1]

            self.assertNotEqual(first_code, second_code)
            # The superseded code no longer works; the fresh one does.
            self.assertEqual(
                self.client.post(VERIFY_URL, {"code": first_code}).status_code, status.HTTP_400_BAD_REQUEST
            )
            self.assertEqual(self.client.post(VERIFY_URL, {"code": second_code}).status_code, status.HTTP_200_OK)

    @pytest.mark.disable_mock_code_based_verifier
    def test_resend_does_not_reset_the_failed_attempt_cap(self):
        with freeze_time("2024-01-01T10:00:00") as frozen, enable_code_sending() as mock_send:
            code = self._trigger(mock_send)
            wrong = "000000" if code != "000000" else "111111"

            # Use up all but one of the attempt budget, then resend to try to reset the counter.
            for _ in range(CODE_MAX_ATTEMPTS - 1):
                self.assertEqual(self.client.post(VERIFY_URL, {"code": wrong}).status_code, status.HTTP_400_BAD_REQUEST)

            frozen.move_to("2024-01-01T10:01:01")  # past the 1/min resend throttle
            self.assertEqual(self.client.post(RESEND_URL).status_code, status.HTTP_200_OK)
            fresh_code = mock_send.call_args[0][1]

            # The resend must not have reset the budget: one more wrong guess hits the cap, and even
            # the freshly-issued correct code is then refused - so the cap can't be replayed in batches.
            self.assertEqual(self.client.post(VERIFY_URL, {"code": wrong}).status_code, status.HTTP_400_BAD_REQUEST)
            response = self.client.post(VERIFY_URL, {"code": fresh_code})
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.json()["code"], "too_many_attempts")
