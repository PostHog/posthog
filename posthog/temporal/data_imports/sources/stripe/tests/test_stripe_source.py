import pytest

from posthog.temporal.data_imports.sources.stripe.source import StripeSource

from products.data_warehouse.backend.types import ExternalDataSourceType


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
