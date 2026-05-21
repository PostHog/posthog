import pytest

from posthog.temporal.data_imports.sources.google_ads.source import GoogleAdsSource


class TestGoogleAdsNonRetryableErrors:
    def setup_method(self):
        self.source = GoogleAdsSource()

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Observed in production: requesting metrics against a manager (MCC) account
            (
                "errors {\n  error_code {\n    query_error: REQUESTED_METRICS_FOR_MANAGER\n  }\n  "
                'message: "Metrics cannot be requested for a manager account. To retrieve metrics, '
                'issue separate requests against each client account under the manager account."\n}\n'
            ),
            "PERMISSION_DENIED",
            "UNAUTHENTICATED",
            "ACCESS_TOKEN_SCOPE_INSUFFICIENT",
            "Account has been deleted",
            "INVALID_CUSTOMER_ID",
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
    def test_user_errors_are_non_retryable(self, error_msg):
        non_retryable = self.source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable)
        assert is_non_retryable, f"Expected user-config error to be non-retryable: {error_msg}"

    def test_requested_metrics_for_manager_has_user_facing_message(self):
        non_retryable = self.source.get_non_retryable_errors()
        message = non_retryable["REQUESTED_METRICS_FOR_MANAGER"]
        assert message is not None
        assert "manager" in message.lower()

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
