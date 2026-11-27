from uuid import uuid4

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from django.contrib.sessions.backends.signed_cookies import SessionStore
from django.test import RequestFactory, SimpleTestCase

from parameterized import parameterized

from posthog.helpers.two_factor_session import (
    CODE_BASED_VERIFICATION_IDENTITY_SESSION_KEY,
    CODE_TTL_SECONDS,
    NO_EMAIL_HTTP_SERVICE,
    CodeBasedVerifier,
)
from posthog.redis import TEST_clear_clients, get_client


@pytest.mark.disable_mock_code_based_verifier
@patch("posthog.helpers.two_factor_session.is_dev_mode", return_value=False)
@patch("posthog.helpers.two_factor_session.is_email_available", return_value=True)
class TestCodeBasedVerifierEmailTransport(SimpleTestCase):
    def setUp(self):
        self.mock_user = MagicMock()
        self.mock_user.pk = 123
        self.mock_user.email = "test@example.com"
        self.mock_user.distinct_id = uuid4()

    @patch("posthog.helpers.two_factor_session.is_http_email_service_available", return_value=True)
    def test_sends_the_code_when_http_email_is_available(self, *_mocks):
        self.assertTrue(CodeBasedVerifier().should_send_code_based_verification(self.mock_user))

    @patch("posthog.helpers.two_factor_session.is_http_email_service_available", return_value=False)
    @patch("posthog.helpers.two_factor_session.posthoganalytics.capture")
    def test_no_http_service_bypasses_mfa(self, mock_capture, *_mocks):
        self.assertFalse(CodeBasedVerifier().should_send_code_based_verification(self.mock_user))
        self.assertEqual(mock_capture.call_args.kwargs["event"], "code_based_verification_bypassed_due_to_suppression")
        self.assertEqual(mock_capture.call_args.kwargs["properties"]["reason"], NO_EMAIL_HTTP_SERVICE)

    @parameterized.expand(
        [
            ("cloud_with_smtp", True, True),
            ("cloud_without_any_email", True, False),
            ("self_hosted", False, True),
        ]
    )
    @patch("posthog.helpers.two_factor_session.is_http_email_service_available", return_value=False)
    @patch("posthog.helpers.two_factor_session.posthoganalytics.capture")
    @patch("posthog.helpers.two_factor_session.capture_exception")
    def test_no_http_service_on_cloud_reports_the_skipped_login_code(
        self, _name, on_cloud, email_available, mock_capture_exception, *_mocks
    ):
        with (
            patch("posthog.helpers.two_factor_session.is_cloud", return_value=on_cloud),
            patch("posthog.helpers.two_factor_session.is_email_available", return_value=email_available),
        ):
            CodeBasedVerifier().should_send_code_based_verification(self.mock_user)

        self.assertEqual(mock_capture_exception.called, on_cloud)


@pytest.mark.disable_mock_code_based_verifier
class TestCodeBasedVerifierAttempts(SimpleTestCase):
    @parameterized.expand([("new", False), ("interrupted_expiry", True)])
    def test_idp_attempts_expire_without_renewing_the_window(self, _name: str, missing_expiry: bool) -> None:
        TEST_clear_clients()
        self.addCleanup(TEST_clear_clients)
        verifier = CodeBasedVerifier()
        request = RequestFactory().post("/")
        request.session = SessionStore()
        request.session.update(
            {
                "code_based_verification_pending_user_id": 123,
                CODE_BASED_VERIFICATION_IDENTITY_SESSION_KEY: "example-subject",
            }
        )
        with time_machine.travel("2026-01-10T12:00:00Z", tick=False) as clock:
            if missing_expiry:
                get_client().set(verifier._attempts_redis_key("idp:example-subject"), 1)
            self.assertEqual(verifier.reserve_attempt(request), 2 if missing_expiry else 1)
            clock.shift(CODE_TTL_SECONDS - 1)
            self.assertEqual(verifier.reserve_attempt(request), 3 if missing_expiry else 2)
            clock.shift(2)
            self.assertEqual(verifier.reserve_attempt(request), 1)
