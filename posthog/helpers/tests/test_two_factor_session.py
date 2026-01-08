from uuid import uuid4

import pytest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from posthog.helpers.email_utils import ESPSuppressionResult
from posthog.helpers.two_factor_session import EmailMFACheckResult, EmailMFAVerifier


@pytest.mark.disable_mock_email_mfa_verifier
class TestEmailMFAVerifierSuppressionIntegration(SimpleTestCase):
    def setUp(self):
        self.mock_user = MagicMock()
        self.mock_user.pk = 123
        self.mock_user.email = "test@example.com"
        self.mock_user.distinct_id = uuid4()
        self.mock_user.organization = MagicMock()
        self.mock_user.organization.id = uuid4()

    @patch("posthog.helpers.two_factor_session.is_dev_mode")
    @patch("posthog.helpers.two_factor_session.is_email_available")
    @patch("posthog.helpers.two_factor_session.posthoganalytics.feature_enabled")
    @patch("posthog.helpers.two_factor_session.check_esp_suppression")
    def test_suppressed_user_skips_email_mfa(
        self, mock_check_suppression, mock_feature_enabled, mock_email_available, mock_dev_mode
    ):
        mock_dev_mode.return_value = False
        mock_email_available.return_value = True
        mock_feature_enabled.return_value = True
        mock_check_suppression.return_value = ESPSuppressionResult(
            is_suppressed=True, from_cache=False, reason="suppressed"
        )

        verifier = EmailMFAVerifier()
        result = verifier.should_send_email_mfa_verification(self.mock_user)

        self.assertFalse(result.should_send)
        self.assertTrue(result.suppression_bypassed)
        self.assertEqual(result.suppression_reason, "suppressed")

    @patch("posthog.helpers.two_factor_session.is_dev_mode")
    @patch("posthog.helpers.two_factor_session.is_email_available")
    @patch("posthog.helpers.two_factor_session.posthoganalytics.feature_enabled")
    @patch("posthog.helpers.two_factor_session.check_esp_suppression")
    def test_non_suppressed_user_proceeds_with_email_mfa(
        self, mock_check_suppression, mock_feature_enabled, mock_email_available, mock_dev_mode
    ):
        mock_dev_mode.return_value = False
        mock_email_available.return_value = True
        mock_feature_enabled.return_value = True
        mock_check_suppression.return_value = ESPSuppressionResult(is_suppressed=False, from_cache=False, reason=None)

        verifier = EmailMFAVerifier()
        result = verifier.should_send_email_mfa_verification(self.mock_user)

        self.assertTrue(result.should_send)
        self.assertFalse(result.suppression_bypassed)

    @patch("posthog.helpers.two_factor_session.is_dev_mode")
    @patch("posthog.helpers.two_factor_session.is_email_available")
    @patch("posthog.helpers.two_factor_session.posthoganalytics.feature_enabled")
    @patch("posthog.helpers.two_factor_session.check_esp_suppression")
    @patch("posthog.helpers.two_factor_session.posthoganalytics.capture")
    def test_analytics_event_captured_on_suppression_bypass(
        self, mock_capture, mock_check_suppression, mock_feature_enabled, mock_email_available, mock_dev_mode
    ):
        mock_dev_mode.return_value = False
        mock_email_available.return_value = True
        mock_feature_enabled.return_value = True
        mock_check_suppression.return_value = ESPSuppressionResult(
            is_suppressed=True, from_cache=False, reason="suppressed"
        )

        verifier = EmailMFAVerifier()
        verifier.should_send_email_mfa_verification(self.mock_user)

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args[1]
        self.assertEqual(call_kwargs["event"], "email_mfa_bypassed_due_to_suppression")
        self.assertEqual(call_kwargs["distinct_id"], str(self.mock_user.distinct_id))

    @patch("posthog.helpers.two_factor_session.is_dev_mode")
    @patch("posthog.helpers.two_factor_session.is_email_available")
    @patch("posthog.helpers.two_factor_session.posthoganalytics.feature_enabled")
    @patch("posthog.helpers.two_factor_session.check_esp_suppression")
    @patch("posthog.helpers.two_factor_session.posthoganalytics.capture")
    def test_analytics_event_includes_correct_properties(
        self, mock_capture, mock_check_suppression, mock_feature_enabled, mock_email_available, mock_dev_mode
    ):
        mock_dev_mode.return_value = False
        mock_email_available.return_value = True
        mock_feature_enabled.return_value = True
        mock_check_suppression.return_value = ESPSuppressionResult(
            is_suppressed=True, from_cache=True, reason="suppressed"
        )

        verifier = EmailMFAVerifier()
        verifier.should_send_email_mfa_verification(self.mock_user)

        call_kwargs = mock_capture.call_args[1]
        self.assertEqual(call_kwargs["properties"]["reason"], "suppressed")
        self.assertTrue(call_kwargs["properties"]["cached"])

    @patch("posthog.helpers.two_factor_session.is_dev_mode")
    @patch("posthog.helpers.two_factor_session.is_email_available")
    @patch("posthog.helpers.two_factor_session.posthoganalytics.feature_enabled")
    @patch("posthog.helpers.two_factor_session.check_esp_suppression")
    @patch("posthog.helpers.two_factor_session.posthoganalytics.capture")
    def test_api_failure_fallback_bypasses_mfa_and_captures_event(
        self, mock_capture, mock_check_suppression, mock_feature_enabled, mock_email_available, mock_dev_mode
    ):
        mock_dev_mode.return_value = False
        mock_email_available.return_value = True
        mock_feature_enabled.return_value = True
        mock_check_suppression.return_value = ESPSuppressionResult(
            is_suppressed=True, from_cache=False, reason="api_failure_fallback"
        )

        verifier = EmailMFAVerifier()
        result = verifier.should_send_email_mfa_verification(self.mock_user)

        self.assertFalse(result.should_send)
        self.assertTrue(result.suppression_bypassed)
        self.assertEqual(result.suppression_reason, "api_failure_fallback")

        call_kwargs = mock_capture.call_args[1]
        self.assertEqual(call_kwargs["properties"]["reason"], "api_failure_fallback")
        self.assertFalse(call_kwargs["properties"]["cached"])

    @patch("posthog.helpers.two_factor_session.is_dev_mode")
    @patch("posthog.helpers.two_factor_session.is_email_available")
    @patch("posthog.helpers.two_factor_session.posthoganalytics.feature_enabled")
    @patch("posthog.helpers.two_factor_session.check_esp_suppression")
    def test_returns_email_mfa_check_result(
        self, mock_check_suppression, mock_feature_enabled, mock_email_available, mock_dev_mode
    ):
        mock_dev_mode.return_value = False
        mock_email_available.return_value = True
        mock_feature_enabled.return_value = True
        mock_check_suppression.return_value = ESPSuppressionResult(
            is_suppressed=True, from_cache=False, reason="suppressed"
        )

        verifier = EmailMFAVerifier()
        result = verifier.should_send_email_mfa_verification(self.mock_user)

        self.assertIsInstance(result, EmailMFACheckResult)
        self.assertFalse(result.should_send)
