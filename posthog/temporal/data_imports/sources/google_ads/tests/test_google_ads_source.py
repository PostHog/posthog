import pytest

from posthog.temporal.data_imports.sources.google_ads.source import GoogleAdsSource


class TestGoogleAdsNonRetryableErrors:
    def setup_method(self):
        self.source = GoogleAdsSource()
        self.non_retryable = self.source.get_non_retryable_errors()

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
        assert any(pattern in error_msg for pattern in self.non_retryable), (
            f"RefreshError message {error_msg!r} did not match any non-retryable pattern"
        )

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Real RefreshError strings observed in production when a Google Workspace
            # admin has restricted third-party API access for the app. Reported by
            # `str(e)` on google.auth.exceptions.RefreshError.
            (
                "('access_not_configured: Access to your account data (which may include HIPAA and PHI data) is "
                "restricted by policies within your organization. Please contact the administrator of your "
                "organization for more information regarding API access from third-party applications.', "
                "{'error': 'access_not_configured', 'error_description': 'Access to your account data ...'})"
            ),
            (
                "('access_not_configured: You can't access this app until an admin at your institution reviews "
                "and configures access for it. If you need access to this app,', {'error': 'access_not_configured', "
                "'error_description': 'You can't access this app ...'})"
            ),
        ],
    )
    def test_access_not_configured_is_non_retryable(self, error_msg):
        assert any(pattern in error_msg for pattern in self.non_retryable), (
            f"RefreshError message {error_msg!r} did not match any non-retryable pattern"
        )

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Observed in production: requesting metrics against a manager (MCC) account.
            (
                "errors {\n  error_code {\n    query_error: REQUESTED_METRICS_FOR_MANAGER\n  }\n  "
                'message: "Metrics cannot be requested for a manager account. To retrieve metrics, '
                'issue separate requests against each client account under the manager account."\n}\n'
            ),
            # Other Google Ads specific failures that should stop retrying.
            "PERMISSION_DENIED: The caller does not have permission",
            "UNAUTHENTICATED: Request had invalid authentication credentials",
            "ACCESS_TOKEN_SCOPE_INSUFFICIENT: Request had insufficient authentication scopes",
            "Customer: Account has been deleted",
            "INVALID_CUSTOMER_ID: Customer ID is not valid",
        ],
    )
    def test_permanent_auth_errors_are_non_retryable(self, error_msg):
        is_non_retryable = any(pattern in error_msg for pattern in self.non_retryable.keys())
        assert is_non_retryable, f"Expected error to be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Transient network/infrastructure errors should still be retried.
            "DeadlineExceeded: 504 Deadline Exceeded",
            "UNAVAILABLE: The service is currently unavailable",
            "ConnectionError: Connection reset by peer",
            "INTERNAL: Internal server error",
            # A RefreshError wrapping a transient 502 from Google's token endpoint shares the
            # same error-tracking group as access_not_configured but must remain retryable.
            "('<!DOCTYPE html><title>Error 502 (Server Error)!!1</title>', None)",
        ],
    )
    def test_transient_errors_are_retryable(self, error_msg):
        is_non_retryable = any(pattern in error_msg for pattern in self.non_retryable.keys())
        assert not is_non_retryable, f"Expected error to be retryable: {error_msg}"

    @pytest.mark.parametrize(
        "pattern",
        [
            "PERMISSION_DENIED",
            "UNAUTHENTICATED",
            "ACCESS_TOKEN_SCOPE_INSUFFICIENT",
            "Account has been deleted",
            "INVALID_CUSTOMER_ID",
            "REQUESTED_METRICS_FOR_MANAGER",
            "invalid_grant",
            "access_not_configured",
        ],
    )
    def test_documented_patterns_present(self, pattern):
        assert pattern in self.non_retryable

    def test_requested_metrics_for_manager_has_user_facing_message(self):
        message = self.non_retryable["REQUESTED_METRICS_FOR_MANAGER"]
        assert message is not None
        assert "manager" in message.lower()

    def test_invalid_grant_has_friendly_message(self):
        friendly = self.non_retryable["invalid_grant"]
        assert friendly is not None
        assert "reconnect" in friendly.lower()

    def test_access_not_configured_has_friendly_message(self):
        friendly = self.non_retryable["access_not_configured"]
        assert friendly is not None
        assert "admin" in friendly.lower()
