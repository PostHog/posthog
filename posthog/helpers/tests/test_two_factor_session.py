from uuid import uuid4

import pytest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.helpers.two_factor_session import NO_EMAIL_HTTP_SERVICE, CodeBasedVerifier


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
