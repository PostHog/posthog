import pytest

from posthog.temporal.data_imports.sources.google_ads.source import GoogleAdsSource


class TestGoogleAdsNonRetryableErrors:
    def setup_method(self):
        self.source = GoogleAdsSource()

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Real RefreshError string observed in production when the refresh
            # token has been revoked / expired — reported by `str(e)` on
            # google.auth.exceptions.RefreshError.
            "('invalid_grant: Bad Request', {'error': 'invalid_grant', 'error_description': 'Bad Request'})",
            "('invalid_grant: Token has been expired or revoked.', {'error': 'invalid_grant', 'error_description': 'Token has been expired or revoked.'})",
            "('invalid_grant: Invalid grant: account not found', {'error': 'invalid_grant', 'error_description': 'Invalid grant: account not found'})",
        ],
    )
    def test_invalid_grant_is_non_retryable(self, error_msg):
        non_retryable = self.source.get_non_retryable_errors()
        assert any(pattern in error_msg for pattern in non_retryable), (
            f"RefreshError message {error_msg!r} did not match any non-retryable pattern"
        )

    @pytest.mark.parametrize(
        "pattern",
        [
            "PERMISSION_DENIED",
            "UNAUTHENTICATED",
            "ACCESS_TOKEN_SCOPE_INSUFFICIENT",
            "Account has been deleted",
            "INVALID_CUSTOMER_ID",
            "invalid_grant",
        ],
    )
    def test_documented_patterns_present(self, pattern):
        assert pattern in self.source.get_non_retryable_errors()
