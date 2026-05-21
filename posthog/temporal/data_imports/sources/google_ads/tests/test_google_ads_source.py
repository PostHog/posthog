import pytest

from posthog.temporal.data_imports.sources.google_ads.source import GoogleAdsSource


class TestGoogleAdsNonRetryableErrors:
    def setup_method(self):
        self.source = GoogleAdsSource()

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Exact excerpt reported by error tracking.
            "RefreshError: ('invalid_grant: Token has been expired or revoked.', "
            "{'error': 'invalid_grant', 'error_description': 'Token has been expired or revoked.'})",
            # Second common variant from error tracking (same root cause — revoked/expired refresh token).
            "RefreshError: ('invalid_grant: Bad Request', "
            "{'error': 'invalid_grant', 'error_description': 'Bad Request'})",
            # Other Google Ads specific failures that should stop retrying.
            "PERMISSION_DENIED: The caller does not have permission",
            "UNAUTHENTICATED: Request had invalid authentication credentials",
            "ACCESS_TOKEN_SCOPE_INSUFFICIENT: Request had insufficient authentication scopes",
            "Customer: Account has been deleted",
            "INVALID_CUSTOMER_ID: Customer ID is not valid",
        ],
    )
    def test_permanent_auth_errors_are_non_retryable(self, error_msg):
        non_retryable = self.source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Expected error to be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Transient network/infrastructure errors should still be retried.
            "DeadlineExceeded: 504 Deadline Exceeded",
            "UNAVAILABLE: The service is currently unavailable",
            "ConnectionError: Connection reset by peer",
            "INTERNAL: Internal server error",
        ],
    )
    def test_transient_errors_are_retryable(self, error_msg):
        non_retryable = self.source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert not is_non_retryable, f"Expected error to be retryable: {error_msg}"

    def test_invalid_grant_has_friendly_message(self):
        non_retryable = self.source.get_non_retryable_errors()
        assert "invalid_grant" in non_retryable
        friendly = non_retryable["invalid_grant"]
        assert friendly is not None
        assert "reconnect" in friendly.lower()
