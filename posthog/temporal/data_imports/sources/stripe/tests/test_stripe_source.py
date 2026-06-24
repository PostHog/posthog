from typing import Any, cast

import pytest
from unittest import mock
from unittest.mock import MagicMock, patch

import stripe as stripe_lib
from stripe import ListObject

from posthog.temporal.data_imports.sources.generated_configs import StripeAuthMethodConfig, StripeSourceConfig
from posthog.temporal.data_imports.sources.stripe import stripe as stripe_module
from posthog.temporal.data_imports.sources.stripe.constants import (
    CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
)
from posthog.temporal.data_imports.sources.stripe.source import StripeSource
from posthog.temporal.data_imports.sources.stripe.stripe import (
    StripeAuthenticationError,
    StripeNestedResource,
    StripeResource,
    _coerce_incremental_cursor,
    get_rows,
)


def _list_object(items):
    obj = MagicMock()
    obj.auto_paging_iter.return_value = iter(items)
    return obj


class _FakeStripeList:
    def __init__(self, objects):
        self._objects = objects

    def auto_paging_iter(self):
        return iter(self._objects)


class TestStripeGetRowsIncrementalCursor:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (1700000000, 1700000000),
            (1700000000.0, 1700000000),
            # The persisted watermark is read back from JSON config as a numeric string.
            ("1700000000", 1700000000),
            (None, None),
            ("not-a-timestamp", None),
            (True, None),
        ],
    )
    def test_coerce_incremental_cursor(self, value, expected):
        assert _coerce_incremental_cursor(value) == expected

    def test_get_rows_handles_string_incremental_watermark(self):
        # Stripe object timestamps are ints, but the stored watermark can come back as a numeric
        # string. The cursor comparison must not crash with `'<=' not supported between instances
        # of 'int' and 'str'`, and must still stop once it reaches an object at/under the watermark.
        objects = [
            {"id": "ch_2", "created": 1700000100},
            {"id": "ch_1", "created": 1700000040},
        ]
        resource = StripeResource(method=lambda params: cast(ListObject[Any], _FakeStripeList(objects)))
        resumable_source_manager = mock.MagicMock()
        resumable_source_manager.can_resume.return_value = False

        with mock.patch(
            "posthog.temporal.data_imports.sources.stripe.stripe._build_resources",
            return_value={"charge": resource},
        ):
            rows = list(
                get_rows(
                    api_key="sk_test_123",
                    endpoint="charge",
                    account_id=None,
                    db_incremental_field_last_value="1700000050",
                    db_incremental_field_earliest_value=None,
                    logger=mock.MagicMock(),
                    resumable_source_manager=resumable_source_manager,
                    should_use_incremental_field=True,
                )
            )

        assert [obj["id"] for obj in rows] == ["ch_2"]


class TestStripeSource:
    def setup_method(self):
        self.source = StripeSource()

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
            # IP allowlist rejection — matched on the stable phrase, ignoring the appended IP address.
            "The API key provided does not allow requests from your IP address.",
            "The API key provided does not allow requests from your IP address (1.2.3.4).",
            # account_invalid: key not authorized for the configured account, or revoked app access.
            # Raised mid-sync as stripe.PermissionError, matched on the stable phrase (key/account redacted).
            "The provided key 'sk_test_***qPsl' does not have access to account 'stripe_s***less' (or that account does not exist). Application access may have been revoked.",
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
        "config,expected_message",
        [
            # OAuth selected but the integration was never linked (or was deleted): `_get_api_key`
            # raises ValueError("Missing Stripe integration ID"), an internal string the user can't
            # act on. validate_credentials must translate it to the reconnect guidance.
            (
                StripeSourceConfig(auth_method=StripeAuthMethodConfig(selection="oauth", stripe_integration_id=None)),
                "Stripe integration ID is not configured. Please reconnect your Stripe account.",
            ),
            (
                StripeSourceConfig(auth_method=StripeAuthMethodConfig(selection="api_key", stripe_secret_key=None)),
                "Stripe API key is not configured. Please update the source configuration.",
            ),
        ],
    )
    def test_validate_credentials_missing_config_returns_friendly_message(self, config, expected_message):
        ok, message = self.source.validate_credentials(config, team_id=1)

        assert ok is False
        assert message == expected_message

    def test_validate_credentials_does_not_echo_rejected_key(self):
        # Stripe's 401 body echoes the submitted key verbatim; here the user pasted a password into
        # the key field. The validation message must not leak it into the toast or analytics event.
        pasted_secret = "Ammgad1979@"
        config = StripeSourceConfig(
            auth_method=StripeAuthMethodConfig(selection="api_key", stripe_secret_key=pasted_secret)
        )

        with mock.patch(
            "posthog.temporal.data_imports.sources.stripe.source.validate_stripe_credentials",
            side_effect=StripeAuthenticationError(f"Invalid API Key provided: {pasted_secret}"),
        ):
            ok, message = self.source.validate_credentials(config, team_id=1)

        assert ok is False
        assert message is not None
        assert pasted_secret not in message
        assert message.startswith("Stripe rejected the API key.")


def _run_nested_get_rows(nested_method):
    parent = StripeResource(
        method=lambda **kwargs: _list_object([{"id": "cus_ok1"}, {"id": "cus_gone"}, {"id": "cus_ok2"}])
    )
    resource = StripeNestedResource(
        method=nested_method,
        nested_parent_param="customer",
        parent_id="id",
        parent=parent,
        parent_name=CUSTOMER_RESOURCE_NAME,
    )

    resumable_source_manager = MagicMock()
    resumable_source_manager.can_resume.return_value = False

    with (
        patch.object(stripe_module, "StripeClient"),
        patch.object(
            stripe_module,
            "_build_resources",
            return_value={CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME: resource},
        ),
    ):
        rows: list[dict] = []
        for table in get_rows(
            api_key="sk_test_123",
            endpoint=CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME,
            account_id=None,
            db_incremental_field_last_value=None,
            db_incremental_field_earliest_value=None,
            logger=MagicMock(),
            resumable_source_manager=resumable_source_manager,
        ):
            rows.extend(table.to_pylist())
    return rows


class TestStripeNestedResourceGetRows:
    def test_skips_parent_deleted_mid_sync(self):
        def nested_method(customer=None, params=None):
            if customer == "cus_gone":
                raise stripe_lib.InvalidRequestError(
                    f"No such customer: '{customer}'", "customer", code="resource_missing", http_status=404
                )
            return _list_object([{"id": f"cbt_{customer}", "amount": 100}])

        rows = _run_nested_get_rows(nested_method)

        assert {row["customer"] for row in rows} == {"cus_ok1", "cus_ok2"}

    def test_other_invalid_request_errors_still_raise(self):
        def nested_method(customer=None, params=None):
            raise stripe_lib.InvalidRequestError("Invalid string", "expand", code="parameter_unknown", http_status=400)

        with pytest.raises(stripe_lib.InvalidRequestError):
            _run_nested_get_rows(nested_method)
