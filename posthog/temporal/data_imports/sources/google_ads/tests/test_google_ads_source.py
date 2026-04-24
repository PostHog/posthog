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
