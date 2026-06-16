import pytest
from unittest import mock

from posthog.temporal.data_imports.sources.generated_configs import LinkedinAdsSourceConfig
from posthog.temporal.data_imports.sources.linkedin_ads.source import LinkedInAdsSource


class TestLinkedInAdsSource:
    """Test suite for LinkedInAdsSource class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.source = LinkedInAdsSource()
        self.team_id = 123
        self.config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=456, account_id="789")

    def test_validate_credentials_missing_account_id(self):
        """Test credential validation with missing account ID."""
        invalid_config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=456, account_id="")

        is_valid, error_message = self.source.validate_credentials(invalid_config, self.team_id)

        assert is_valid is False
        assert error_message is not None
        assert "Account ID and LinkedIn Ads integration are required" in error_message

    @mock.patch("posthog.temporal.data_imports.sources.linkedin_ads.source.Integration")
    def test_validate_credentials_integration_not_found(self, mock_integration_model):
        """Test credential validation when integration doesn't exist."""

        # Mock DoesNotExist exception
        class MockDoesNotExist(Exception):
            pass

        mock_integration_model.DoesNotExist = MockDoesNotExist
        mock_integration_model.objects.get.side_effect = MockDoesNotExist()

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message is not None
        assert "LinkedIn Ads integration not found" in error_message

    @mock.patch("posthog.temporal.data_imports.sources.linkedin_ads.source.Integration")
    @mock.patch("posthog.temporal.data_imports.sources.linkedin_ads.source.capture_exception")
    def test_validate_credentials_unexpected_error(self, mock_capture_exception, mock_integration_model):
        """Test credential validation with unexpected error."""

        # Mock DoesNotExist exception
        class MockDoesNotExist(Exception):
            pass

        mock_integration_model.DoesNotExist = MockDoesNotExist
        mock_integration_model.objects.get.side_effect = Exception("Database error")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message is not None
        assert "Failed to validate LinkedIn Ads credentials" in error_message
        assert "Database error" in error_message
        mock_capture_exception.assert_called_once()

    @pytest.mark.parametrize(
        "observed_error",
        [
            # A non-numeric Account ID raises this 400 — the quoted key value is volatile, the
            # type-coercion phrase is the stable part we match on.
            'LinkedIn API error (400): {"message":"Key value \'Reed%20Lnkedin\' must be of type \'java.lang.Long\'","status":400}',
            'LinkedIn API error (400): {"message":"Key value \'LI\' must be of type \'java.lang.Long\'","status":400}',
            # Same root cause via the analytics endpoint, which sends the account as a
            # `urn:li:sponsoredAccount:<id>` URN — a non-numeric id makes the URN undeserializable.
            "LinkedIn API error (400): {\"message\":\"Array parameter 'accounts' value 'urn:li:sponsoredAccount:Futuros' is invalid. Reason: Deserializing output 'urn:li:sponsoredAccount:Futuros' failed\",\"status\":400}",
        ],
    )
    def test_non_retryable_errors_match_invalid_account_id(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            # Transient transport / 5xx errors must stay retryable.
            "LinkedIn API error (retryable, 503): service unavailable",
            'LinkedIn daily rate limit reached (429): {"message":"throttled","status":429}',
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "pattern,raised_message",
        [
            (
                "No virtual resource found",
                'LinkedIn API error (404): {"status":404,"code":"RESOURCE_NOT_FOUND","message":"No virtual resource found"}',
            ),
            (
                "The token used in the request has expired",
                "LinkedIn API error (401): The token used in the request has expired",
            ),
        ],
    )
    def test_get_non_retryable_errors_pattern_recognised(self, pattern, raised_message):
        non_retryable_errors = self.source.get_non_retryable_errors()

        assert pattern in non_retryable_errors
        assert pattern in raised_message

    @pytest.mark.parametrize(
        "transient_message",
        [
            # Transient transport / 5xx failures must stay retryable — matching any of these would
            # disable the schema sync after a handful of recoverable blips.
            "LinkedIn API error (retryable, 500): Internal Server Error",
            "LinkedIn API error (retryable, 504): Gateway Timeout",
            "ConnectionError: HTTPSConnectionPool(host='api.linkedin.com', port=443): Max retries exceeded",
            "ReadTimeout: The read operation timed out",
        ],
    )
    def test_get_non_retryable_errors_does_not_match_transient_failures(self, transient_message):
        non_retryable_errors = self.source.get_non_retryable_errors()

        assert not any(pattern in transient_message for pattern in non_retryable_errors)
