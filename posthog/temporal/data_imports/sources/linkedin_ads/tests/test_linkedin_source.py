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
            'LinkedIn daily rate limit reached (429): {"status":429,"serviceErrorCode":101,"code":"TOO_MANY_REQUESTS","message":"Resource level throttle APPLICATION_AND_MEMBER DAY limit for calls to this resource is reached."}',
            "LinkedinAdsDailyRateLimitError: LinkedIn daily rate limit reached (429): {}",
        ],
    )
    def test_non_retryable_errors_match_daily_rate_limit(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            # Short-window 429s stay retryable — they are not the daily budget throttle.
            'LinkedIn API error (retryable, 429): {"message":"Resource throttle MINUTE limit reached."}',
            "LinkedIn API error (retryable, 503): service unavailable",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)
