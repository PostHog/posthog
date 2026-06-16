import pytest

from stripe import PermissionError as StripePermissionError

from posthog.temporal.data_imports.sources.stripe.source import StripeSource

from products.data_warehouse.backend.types import ExternalDataSourceType


def _is_non_retryable(source: StripeSource, error_msg: str) -> bool:
    # Mirror the matcher in import_data_sync / external_data_job: substring match of each
    # non-retryable key against the raw exception string.
    return any(key in error_msg for key in source.get_non_retryable_errors())


class TestStripeSource:
    def setup_method(self):
        self.source = StripeSource()

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.STRIPE

    @pytest.mark.parametrize(
        "observed_error",
        [
            # 403 raised mid-sync — `str(StripeError)` is "Request <id>: <message>", with no class
            # name, so these are matched on the stable message text rather than "PermissionError".
            "Request req_Zb0EgUuheEd4gf: Permission denied. The provided key 'rk_live_***j4va7j' does not have the required permissions for this endpoint on account 'acct_123'. Enabling \"Prices Read\" ('plan_read') permissions on this key would allow this request to continue.",
            "Request req_abc123: Only Stripe Connect platforms can work with other accounts. If you specified a client_id parameter, make sure it's correct.",
            # 401/403 surfaced as a requests HTTPError keep matching the existing URL-based keys.
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "403 Client Error: Forbidden for url: https://api.stripe.com/v1/prices",
        ],
    )
    def test_non_retryable_errors_match_permission_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            # Transient/infra errors must stay retryable.
            "HTTPSConnectionPool(host='api.stripe.com', port=443): Read timed out.",
            "500 Server Error: Internal Server Error for url: https://api.stripe.com/v1/charges",
            "Connection reset by peer",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "scope_message",
        [
            # Restricted key missing the Credit Notes Read scope.
            (
                "Permission denied. The provided key 'rk_live_xxxx' does not have the required "
                "permissions for this endpoint on account 'acct_1'. Enabling \"Credit Notes Read\" "
                "('credit_note_read') permissions on this key would allow this request to continue. "
                "You can edit permissions at https://dashboard.stripe.com/..."
            ),
            # Same shape for any other missing resource scope (Stripe's phrasing is stable).
            (
                "Permission denied. The provided key 'rk_live_yyyy' does not have the required "
                "permissions for this endpoint on account 'acct_2'. Having the 'rak_payment_method_read' "
                "permission would allow this request to continue."
            ),
        ],
    )
    def test_missing_scope_permission_error_is_non_retryable(self, scope_message: str) -> None:
        # Build the real exception string the SDK raises (includes request id prefix) so the test
        # would have caught the bug where the message never contained the literal "PermissionError".
        error = StripePermissionError(scope_message)
        error.request_id = "req_zpuHpEJEXoOIl2"
        error_msg = str(error)

        assert "PermissionError" not in error_msg
        assert _is_non_retryable(self.source, error_msg)
