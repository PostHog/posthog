from uuid import uuid4

import pytest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.helpers.email_utils import ESPSuppressionReason, ESPSuppressionResult
from posthog.helpers.two_factor_session import (
    MAX_EMAIL_MFA_GLOBAL_DISABLE_TTL_SECONDS,
    EmailMFACheckResult,
    EmailMFAVerifier,
    clear_email_mfa_global_disable,
    get_email_mfa_global_disable,
    is_email_mfa_globally_disabled,
    set_email_mfa_global_disable,
)


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
    @patch("posthog.helpers.two_factor_session.is_http_email_service_available")
    @patch("posthog.helpers.two_factor_session.posthoganalytics.feature_enabled")
    @patch("posthog.helpers.two_factor_session.check_esp_suppression")
    def test_suppressed_user_skips_email_mfa(
        self, mock_check_suppression, mock_feature_enabled, mock_http_available, mock_email_available, mock_dev_mode
    ):
        mock_dev_mode.return_value = False
        mock_email_available.return_value = True
        mock_http_available.return_value = True
        mock_feature_enabled.return_value = True
        mock_check_suppression.return_value = ESPSuppressionResult(
            is_suppressed=True, from_cache=False, reason=ESPSuppressionReason.SUPPRESSED
        )

        verifier = EmailMFAVerifier()
        result = verifier.should_send_email_mfa_verification(self.mock_user)

        self.assertFalse(result.should_send)
        self.assertTrue(result.suppression_bypassed)
        self.assertEqual(result.suppression_reason, ESPSuppressionReason.SUPPRESSED)

    @patch("posthog.helpers.two_factor_session.is_dev_mode")
    @patch("posthog.helpers.two_factor_session.is_email_available")
    @patch("posthog.helpers.two_factor_session.is_http_email_service_available")
    @patch("posthog.helpers.two_factor_session.posthoganalytics.feature_enabled")
    @patch("posthog.helpers.two_factor_session.check_esp_suppression")
    def test_non_suppressed_user_proceeds_with_email_mfa(
        self, mock_check_suppression, mock_feature_enabled, mock_http_available, mock_email_available, mock_dev_mode
    ):
        mock_dev_mode.return_value = False
        mock_email_available.return_value = True
        mock_http_available.return_value = True
        mock_feature_enabled.return_value = True
        mock_check_suppression.return_value = ESPSuppressionResult(is_suppressed=False, from_cache=False, reason=None)

        verifier = EmailMFAVerifier()
        result = verifier.should_send_email_mfa_verification(self.mock_user)

        self.assertTrue(result.should_send)
        self.assertFalse(result.suppression_bypassed)

    @patch("posthog.helpers.two_factor_session.is_dev_mode")
    @patch("posthog.helpers.two_factor_session.is_email_available")
    @patch("posthog.helpers.two_factor_session.is_http_email_service_available")
    @patch("posthog.helpers.two_factor_session.posthoganalytics.feature_enabled")
    @patch("posthog.helpers.two_factor_session.check_esp_suppression")
    @patch("posthog.helpers.two_factor_session.posthoganalytics.capture")
    def test_analytics_event_captured_on_suppression_bypass(
        self,
        mock_capture,
        mock_check_suppression,
        mock_feature_enabled,
        mock_http_available,
        mock_email_available,
        mock_dev_mode,
    ):
        mock_dev_mode.return_value = False
        mock_email_available.return_value = True
        mock_http_available.return_value = True
        mock_feature_enabled.return_value = True
        mock_check_suppression.return_value = ESPSuppressionResult(
            is_suppressed=True, from_cache=False, reason=ESPSuppressionReason.SUPPRESSED
        )

        verifier = EmailMFAVerifier()
        verifier.should_send_email_mfa_verification(self.mock_user)

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args[1]
        self.assertEqual(call_kwargs["event"], "email_mfa_bypassed_due_to_suppression")
        self.assertEqual(call_kwargs["distinct_id"], str(self.mock_user.distinct_id))

    @patch("posthog.helpers.two_factor_session.is_dev_mode")
    @patch("posthog.helpers.two_factor_session.is_email_available")
    @patch("posthog.helpers.two_factor_session.is_http_email_service_available")
    @patch("posthog.helpers.two_factor_session.posthoganalytics.feature_enabled")
    @patch("posthog.helpers.two_factor_session.check_esp_suppression")
    @patch("posthog.helpers.two_factor_session.posthoganalytics.capture")
    def test_analytics_event_includes_correct_properties(
        self,
        mock_capture,
        mock_check_suppression,
        mock_feature_enabled,
        mock_http_available,
        mock_email_available,
        mock_dev_mode,
    ):
        mock_dev_mode.return_value = False
        mock_email_available.return_value = True
        mock_http_available.return_value = True
        mock_feature_enabled.return_value = True
        mock_check_suppression.return_value = ESPSuppressionResult(
            is_suppressed=True, from_cache=True, reason=ESPSuppressionReason.SUPPRESSED
        )

        verifier = EmailMFAVerifier()
        verifier.should_send_email_mfa_verification(self.mock_user)

        call_kwargs = mock_capture.call_args[1]
        self.assertEqual(call_kwargs["properties"]["reason"], ESPSuppressionReason.SUPPRESSED)
        self.assertTrue(call_kwargs["properties"]["cached"])

    @patch("posthog.helpers.two_factor_session.is_dev_mode")
    @patch("posthog.helpers.two_factor_session.is_email_available")
    @patch("posthog.helpers.two_factor_session.is_http_email_service_available")
    @patch("posthog.helpers.two_factor_session.posthoganalytics.feature_enabled")
    @patch("posthog.helpers.two_factor_session.check_esp_suppression")
    @patch("posthog.helpers.two_factor_session.posthoganalytics.capture")
    def test_api_failure_fallback_bypasses_mfa_and_captures_event(
        self,
        mock_capture,
        mock_check_suppression,
        mock_feature_enabled,
        mock_http_available,
        mock_email_available,
        mock_dev_mode,
    ):
        mock_dev_mode.return_value = False
        mock_email_available.return_value = True
        mock_http_available.return_value = True
        mock_feature_enabled.return_value = True
        mock_check_suppression.return_value = ESPSuppressionResult(
            is_suppressed=True, from_cache=False, reason=ESPSuppressionReason.API_FAILURE_FALLBACK
        )

        verifier = EmailMFAVerifier()
        result = verifier.should_send_email_mfa_verification(self.mock_user)

        self.assertFalse(result.should_send)
        self.assertTrue(result.suppression_bypassed)
        self.assertEqual(result.suppression_reason, ESPSuppressionReason.API_FAILURE_FALLBACK)

        call_kwargs = mock_capture.call_args[1]
        self.assertEqual(call_kwargs["properties"]["reason"], ESPSuppressionReason.API_FAILURE_FALLBACK)
        self.assertFalse(call_kwargs["properties"]["cached"])

    @patch("posthog.helpers.two_factor_session.is_dev_mode")
    @patch("posthog.helpers.two_factor_session.is_email_available")
    @patch("posthog.helpers.two_factor_session.is_http_email_service_available")
    @patch("posthog.helpers.two_factor_session.posthoganalytics.feature_enabled")
    @patch("posthog.helpers.two_factor_session.check_esp_suppression")
    def test_returns_email_mfa_check_result(
        self, mock_check_suppression, mock_feature_enabled, mock_http_available, mock_email_available, mock_dev_mode
    ):
        mock_dev_mode.return_value = False
        mock_email_available.return_value = True
        mock_http_available.return_value = True
        mock_feature_enabled.return_value = True
        mock_check_suppression.return_value = ESPSuppressionResult(
            is_suppressed=True, from_cache=False, reason=ESPSuppressionReason.SUPPRESSED
        )

        verifier = EmailMFAVerifier()
        result = verifier.should_send_email_mfa_verification(self.mock_user)

        self.assertIsInstance(result, EmailMFACheckResult)
        self.assertFalse(result.should_send)

    @patch("posthog.helpers.two_factor_session.is_dev_mode")
    @patch("posthog.helpers.two_factor_session.is_email_available")
    @patch("posthog.helpers.two_factor_session.is_http_email_service_available")
    @patch("posthog.helpers.two_factor_session.posthoganalytics.capture")
    def test_no_http_service_bypasses_mfa(self, mock_capture, mock_http_available, mock_email_available, mock_dev_mode):
        mock_dev_mode.return_value = False
        mock_email_available.return_value = True
        mock_http_available.return_value = False

        verifier = EmailMFAVerifier()
        result = verifier.should_send_email_mfa_verification(self.mock_user)

        self.assertFalse(result.should_send)
        self.assertTrue(result.suppression_bypassed)
        self.assertEqual(result.suppression_reason, ESPSuppressionReason.NO_EMAIL_HTTP_SERVICE)

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args[1]
        self.assertEqual(call_kwargs["event"], "email_mfa_bypassed_due_to_suppression")
        self.assertEqual(call_kwargs["properties"]["reason"], ESPSuppressionReason.NO_EMAIL_HTTP_SERVICE)


class TestEmailMFAGlobalDisable(SimpleTestCase):
    def setUp(self):
        clear_email_mfa_global_disable()

    def tearDown(self):
        clear_email_mfa_global_disable()

    def test_not_disabled_by_default(self):
        self.assertFalse(is_email_mfa_globally_disabled())
        self.assertIsNone(get_email_mfa_global_disable())

    def test_set_get_clear_round_trip(self):
        set_email_mfa_global_disable(reason="email pipeline down", ttl_seconds=3600, disabled_by="support@posthog.com")

        self.assertTrue(is_email_mfa_globally_disabled())
        state = get_email_mfa_global_disable()
        assert state is not None
        self.assertEqual(state["reason"], "email pipeline down")
        self.assertEqual(state["disabled_by"], "support@posthog.com")
        self.assertIn("disabled_at", state)
        self.assertTrue(0 < state["expires_in_seconds"] <= 3600)

        clear_email_mfa_global_disable()
        self.assertFalse(is_email_mfa_globally_disabled())
        self.assertIsNone(get_email_mfa_global_disable())

    def test_reason_is_stripped_and_required(self):
        with self.assertRaises(ValueError):
            set_email_mfa_global_disable(reason="   ", ttl_seconds=3600, disabled_by="support@posthog.com")
        self.assertFalse(is_email_mfa_globally_disabled())

    @parameterized.expand(
        [
            ("zero", 0),
            ("negative", -1),
            ("over_max", MAX_EMAIL_MFA_GLOBAL_DISABLE_TTL_SECONDS + 1),
        ]
    )
    def test_invalid_ttl_rejected(self, _name, ttl_seconds):
        with self.assertRaises(ValueError):
            set_email_mfa_global_disable(reason="reason", ttl_seconds=ttl_seconds, disabled_by="support@posthog.com")
        self.assertFalse(is_email_mfa_globally_disabled())

    def test_max_ttl_accepted(self):
        set_email_mfa_global_disable(
            reason="reason", ttl_seconds=MAX_EMAIL_MFA_GLOBAL_DISABLE_TTL_SECONDS, disabled_by="support@posthog.com"
        )
        self.assertTrue(is_email_mfa_globally_disabled())

    @pytest.mark.disable_mock_email_mfa_verifier
    def test_global_disable_skips_email_mfa(self):
        user = MagicMock()
        user.pk = 1
        user.email = "user@example.com"

        set_email_mfa_global_disable(reason="email pipeline down", ttl_seconds=3600, disabled_by="support@posthog.com")
        result = EmailMFAVerifier().should_send_email_mfa_verification(user)
        self.assertEqual(result, EmailMFACheckResult(should_send=False))

    @patch("posthog.helpers.two_factor_session.get_client")
    def test_fails_closed_when_redis_unavailable(self, mock_get_client):
        mock_get_client.side_effect = Exception("redis unreachable")
        # Reads must not raise, and must default to "not disabled" so email MFA stays enforced.
        self.assertFalse(is_email_mfa_globally_disabled())
        self.assertIsNone(get_email_mfa_global_disable())
