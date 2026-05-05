import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import stripe as stripe_lib

from posthog.models.integration import Integration
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.generated_configs import StripeSourceConfig
from posthog.temporal.data_imports.sources.stripe.constants import (
    ACCOUNT_RESOURCE_NAME,
    CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME,
    CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME,
)
from posthog.temporal.data_imports.sources.stripe.source import StripeSource
from posthog.temporal.data_imports.sources.stripe.stripe import (
    StripeAuthenticationError,
    StripeNestedResource,
    StripePermissionError,
    StripeResource,
    StripeResumeConfig,
    StripeValidationError,
    _build_resources,
    _clean_stripe_error_message,
    validate_credentials,
)
from posthog.temporal.tests.data_imports.conftest import run_external_data_job_workflow

from products.data_warehouse.backend.models import ExternalDataSchema, ExternalDataSource

from .data import BALANCE_TRANSACTIONS

pytestmark = pytest.mark.usefixtures("minio_client")


@pytest.fixture
def external_data_source(team):
    source = ExternalDataSource.objects.create(
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={
            "auth_method": {"selection": "api_key", "stripe_secret_key": "test-key"},
            "stripe_account_id": "acct_id",
        },
    )
    return source


@pytest.fixture
def external_data_schema_full_refresh(external_data_source, team):
    schema = ExternalDataSchema.objects.create(
        name="BalanceTransaction",
        team_id=team.pk,
        source_id=external_data_source.pk,
        sync_type="full_refresh",
        sync_type_config={},
    )
    return schema


@pytest.fixture
def external_data_schema_incremental(external_data_source, team):
    schema = ExternalDataSchema.objects.create(
        name="BalanceTransaction",
        team_id=team.pk,
        source_id=external_data_source.pk,
        sync_type="incremental",
        sync_type_config={"incremental_field": "created", "incremental_field_type": "integer"},
    )
    return schema


# mock the chunk size to 1 so we can test how iterating over chunks of data works, particularly with updating the
# incremental field last value
@mock.patch("posthog.temporal.data_imports.pipelines.pipeline.batcher.DEFAULT_CHUNK_SIZE", 1)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_source_full_refresh(
    team, mock_stripe_api, external_data_source, external_data_schema_full_refresh
):
    """Test that a full refresh sync works as expected.

    We expect a single API call to be made to our mock Stripe API, which returns all the balance transactions.
    """

    with mock.patch.object(ResumableSourceManager, "save_state") as mock_save_state:
        table_name = "stripe_balancetransaction"
        expected_num_rows = len(BALANCE_TRANSACTIONS)

        await run_external_data_job_workflow(
            team=team,
            external_data_source=external_data_source,
            external_data_schema=external_data_schema_full_refresh,
            table_name=table_name,
            expected_rows_synced=expected_num_rows,
            expected_total_rows=expected_num_rows,
        )

        # Check that the API was called as expected
        api_calls_made = mock_stripe_api.get_all_api_calls()
        assert len(api_calls_made) == 1
        assert api_calls_made[0].url == "https://api.stripe.com/v1/balance_transactions?limit=100"

        # Make sure the last balance transaction ID was saved as the resume point
        assert mock_save_state.call_args[0][0].starting_after == BALANCE_TRANSACTIONS[-1]["id"]


# mock the chunk size to 1 so we can test how iterating over chunks of data works, particularly with updating the
# incremental field last value
@mock.patch("posthog.temporal.data_imports.pipelines.pipeline.batcher.DEFAULT_CHUNK_SIZE", 1)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_source_resuming_full_refresh(
    team, mock_stripe_api, external_data_source, external_data_schema_full_refresh
):
    """Test that resuming a full refresh sync works as expected.

    We expect a single API call to be made to our mock Stripe API, which returns all the balance transactions with a filter.
    """

    starting_after = "customer_id_1"
    with (
        mock.patch.object(ResumableSourceManager, "can_resume", return_value=True),
        mock.patch.object(
            ResumableSourceManager, "load_state", return_value=StripeResumeConfig(starting_after=starting_after)
        ),
        mock.patch.object(ResumableSourceManager, "save_state") as mock_save_state,
    ):
        table_name = "stripe_balancetransaction"
        expected_num_rows = len(BALANCE_TRANSACTIONS)

        await run_external_data_job_workflow(
            team=team,
            external_data_source=external_data_source,
            external_data_schema=external_data_schema_full_refresh,
            table_name=table_name,
            expected_rows_synced=expected_num_rows,
            expected_total_rows=expected_num_rows,
        )

    # Check that the API was called as expected
    api_calls_made = mock_stripe_api.get_all_api_calls()
    assert len(api_calls_made) == 1
    assert (
        api_calls_made[0].url
        == f"https://api.stripe.com/v1/balance_transactions?limit=100&starting_after={starting_after}"
    )

    # Make sure the last balance transaction ID was saved as the resume point
    assert mock_save_state.call_args[0][0].starting_after == BALANCE_TRANSACTIONS[-1]["id"]


# mock the chunk size to 1 so we can test how iterating over chunks of data works, particularly with updating the
# incremental field last value
@mock.patch("posthog.temporal.data_imports.pipelines.pipeline.batcher.DEFAULT_CHUNK_SIZE", 1)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_source_incremental(team, mock_stripe_api, external_data_source, external_data_schema_incremental):
    """Test that an incremental sync works as expected.

    We set the 'max_created' value to the created timestamp of the third item in the BALANCE_TRANSACTIONS list. This
    means on the first sync it will return all the data, except for the most recent 2 balance transactions.

    Then, after resetting the 'max_created' value, we expect the incremental sync to return the most recent 2 balance
    transactions when it is called again.
    """

    table_name = "stripe_balancetransaction"

    # mock the API so it doesn't return all data on initial sync
    third_item_created = BALANCE_TRANSACTIONS[2]["created"]
    mock_stripe_api.set_max_created(third_item_created)
    expected_rows_synced = 3
    expected_total_rows = 3

    await run_external_data_job_workflow(
        team=team,
        external_data_source=external_data_source,
        external_data_schema=external_data_schema_incremental,
        table_name=table_name,
        expected_rows_synced=expected_rows_synced,
        expected_total_rows=expected_total_rows,
    )

    # Check that the API was called as expected
    api_calls_made = mock_stripe_api.get_all_api_calls()
    assert len(api_calls_made) == 1
    assert parse_qs(urlparse(api_calls_made[0].url).query) == {
        "limit": ["100"],
    }

    mock_stripe_api.reset_max_created()
    # run the incremental sync
    # we expect this to bring in 2 more rows
    expected_rows_synced = 2
    expected_total_rows = len(BALANCE_TRANSACTIONS)

    await run_external_data_job_workflow(
        team=team,
        external_data_source=external_data_source,
        external_data_schema=external_data_schema_incremental,
        table_name=table_name,
        expected_rows_synced=expected_rows_synced,
        expected_total_rows=expected_total_rows,
    )

    api_calls_made = mock_stripe_api.get_all_api_calls()
    # Check that the API was called once more
    assert len(api_calls_made) == 3
    assert parse_qs(urlparse(api_calls_made[1].url).query) == {
        "created[lt]": [str(BALANCE_TRANSACTIONS[4]["created"])],
        "limit": ["100"],
    }
    assert parse_qs(urlparse(api_calls_made[2].url).query) == {
        "created[gt]": [f"{third_item_created}"],
        "limit": ["100"],
    }


def test_validate_credentials():
    mock_client = mock.MagicMock()

    # Mock each resource's list method
    mock_client.accounts.list = mock.MagicMock()
    mock_client.balance_transactions.list = mock.MagicMock()
    mock_client.charges.list = mock.MagicMock()
    mock_client.customers.list = mock.MagicMock()
    mock_client.disputes.list = mock.MagicMock()
    mock_client.invoice_items.list = mock.MagicMock()
    mock_client.invoices.list = mock.MagicMock()
    mock_client.payouts.list = mock.MagicMock()
    mock_client.prices.list = mock.MagicMock()
    mock_client.products.list = mock.MagicMock()
    mock_client.subscriptions.list = mock.MagicMock()
    mock_client.refunds.list = mock.MagicMock()
    mock_client.credit_notes.list = mock.MagicMock()

    with mock.patch("posthog.temporal.data_imports.sources.stripe.stripe.StripeClient", return_value=mock_client):
        result = validate_credentials("api_key")

        assert result is True

        mock_client.accounts.list.assert_called_once_with(params={"limit": 1})
        mock_client.balance_transactions.list.assert_called_once_with(params={"limit": 1})
        mock_client.charges.list.assert_called_once_with(params={"limit": 1})
        mock_client.customers.list.assert_called_once_with(params={"limit": 1})
        mock_client.disputes.list.assert_called_once_with(params={"limit": 1})
        mock_client.invoice_items.list.assert_called_once_with(params={"limit": 1})
        mock_client.invoices.list.assert_called_once_with(params={"limit": 1})
        mock_client.payouts.list.assert_called_once_with(params={"limit": 1})
        mock_client.prices.list.assert_called_once_with(params={"limit": 1})
        mock_client.products.list.assert_called_once_with(params={"limit": 1})
        mock_client.subscriptions.list.assert_called_once_with(params={"limit": 1})
        mock_client.refunds.list.assert_called_once_with(params={"limit": 1})
        mock_client.credit_notes.list.assert_called_once_with(params={"limit": 1})


def test_validate_credentials_with_table_name():
    mock_client = mock.MagicMock()

    # Mock each resource's list method
    mock_client.accounts.list = mock.MagicMock()
    mock_client.balance_transactions.list = mock.MagicMock()
    mock_client.charges.list = mock.MagicMock()
    mock_client.customers.list = mock.MagicMock()
    mock_client.disputes.list = mock.MagicMock()
    mock_client.invoice_items.list = mock.MagicMock()
    mock_client.invoices.list = mock.MagicMock()
    mock_client.payouts.list = mock.MagicMock()
    mock_client.prices.list = mock.MagicMock()
    mock_client.products.list = mock.MagicMock()
    mock_client.subscriptions.list = mock.MagicMock()
    mock_client.refunds.list = mock.MagicMock()
    mock_client.credit_notes.list = mock.MagicMock()

    with mock.patch("posthog.temporal.data_imports.sources.stripe.stripe.StripeClient", return_value=mock_client):
        result = validate_credentials("api_key", ACCOUNT_RESOURCE_NAME)

        assert result is True

        # Accounts should be called
        mock_client.accounts.list.assert_called_once_with(params={"limit": 1})

        # No other endpoint should be though
        mock_client.balance_transactions.list.assert_not_called()
        mock_client.charges.list.assert_not_called()
        mock_client.customers.list.assert_not_called()
        mock_client.disputes.list.assert_not_called()
        mock_client.invoice_items.list.assert_not_called()
        mock_client.invoices.list.assert_not_called()
        mock_client.payouts.list.assert_not_called()
        mock_client.prices.list.assert_not_called()
        mock_client.products.list.assert_not_called()
        mock_client.subscriptions.list.assert_not_called()
        mock_client.refunds.list.assert_not_called()
        mock_client.credit_notes.list.assert_not_called()


def test_validate_credentials_authentication_error_short_circuits():
    """An invalid API key (401) must raise StripeAuthenticationError immediately,
    not bucket every resource into StripePermissionError. Otherwise the user sees
    a misleading 'lacks permissions for ALL 13 resources' message and tries to
    grant permissions they already have."""
    mock_client = mock.MagicMock()
    auth_error = stripe_lib.AuthenticationError(message="Invalid API Key provided: rk_live_***")
    # First call (accounts) raises 401 — loop must abort before touching others.
    mock_client.accounts.list = mock.MagicMock(side_effect=auth_error)
    mock_client.balance_transactions.list = mock.MagicMock()
    mock_client.charges.list = mock.MagicMock()

    with (
        mock.patch("posthog.temporal.data_imports.sources.stripe.stripe.StripeClient", return_value=mock_client),
        pytest.raises(StripeAuthenticationError) as e,
    ):
        validate_credentials("api_key")

    assert "Invalid API Key" in str(e.value)
    # Critically: we did not keep banging the API after a 401.
    mock_client.balance_transactions.list.assert_not_called()
    mock_client.charges.list.assert_not_called()


def test_validate_credentials_permission_error_lists_only_403_resources():
    """403 on a single resource must be reported as a per-resource permission gap,
    not poisoned by other unrelated successes."""
    mock_client = mock.MagicMock()
    mock_client.accounts.list = mock.MagicMock()
    mock_client.balance_transactions.list = mock.MagicMock()
    mock_client.charges.list = mock.MagicMock(side_effect=stripe_lib.PermissionError(message="Forbidden"))
    mock_client.customers.list = mock.MagicMock()
    mock_client.disputes.list = mock.MagicMock()
    mock_client.invoice_items.list = mock.MagicMock()
    mock_client.invoices.list = mock.MagicMock()
    mock_client.payouts.list = mock.MagicMock()
    mock_client.prices.list = mock.MagicMock()
    mock_client.products.list = mock.MagicMock()
    mock_client.subscriptions.list = mock.MagicMock()
    mock_client.refunds.list = mock.MagicMock()
    mock_client.credit_notes.list = mock.MagicMock()

    with (
        mock.patch("posthog.temporal.data_imports.sources.stripe.stripe.StripeClient", return_value=mock_client),
        pytest.raises(StripePermissionError) as e,
    ):
        validate_credentials("api_key")

    assert list(e.value.missing_permissions.keys()) == ["Charge"]


def test_validate_credentials_unknown_error_raises_validation_error():
    """Non-403 failures (network, schema, rate limit) are not permission gaps — must raise
    StripeValidationError so the caller surfaces the verbose underlying message rather than
    pretending the customer needs to grant a missing scope."""
    mock_client = mock.MagicMock()
    mock_client.accounts.list = mock.MagicMock()
    mock_client.balance_transactions.list = mock.MagicMock()
    mock_client.charges.list = mock.MagicMock(side_effect=RuntimeError("connection reset by peer"))
    mock_client.customers.list = mock.MagicMock()
    mock_client.disputes.list = mock.MagicMock()
    mock_client.invoice_items.list = mock.MagicMock()
    mock_client.invoices.list = mock.MagicMock()
    mock_client.payouts.list = mock.MagicMock()
    mock_client.prices.list = mock.MagicMock()
    mock_client.products.list = mock.MagicMock()
    mock_client.subscriptions.list = mock.MagicMock()
    mock_client.refunds.list = mock.MagicMock()
    mock_client.credit_notes.list = mock.MagicMock()

    with (
        mock.patch("posthog.temporal.data_imports.sources.stripe.stripe.StripeClient", return_value=mock_client),
        pytest.raises(StripeValidationError) as e,
    ):
        validate_credentials("api_key")

    assert list(e.value.errors.keys()) == ["Charge"]
    assert "connection reset" in e.value.errors["Charge"]
    assert e.value.missing_permissions == {}


def test_validate_credentials_mixed_403_and_unknown_raises_validation_error_with_both():
    """When both true 403s and unknown errors are present, the validation error should win
    (it's the higher-severity signal) but carry the 403s along so callers can show both."""
    mock_client = mock.MagicMock()
    mock_client.accounts.list = mock.MagicMock()
    mock_client.balance_transactions.list = mock.MagicMock()
    mock_client.charges.list = mock.MagicMock(side_effect=RuntimeError("connection reset"))
    mock_client.customers.list = mock.MagicMock()
    mock_client.disputes.list = mock.MagicMock()
    mock_client.invoice_items.list = mock.MagicMock()
    mock_client.invoices.list = mock.MagicMock()
    mock_client.payouts.list = mock.MagicMock()
    mock_client.prices.list = mock.MagicMock()
    mock_client.products.list = mock.MagicMock()
    mock_client.subscriptions.list = mock.MagicMock(side_effect=stripe_lib.PermissionError(message="Forbidden"))
    mock_client.refunds.list = mock.MagicMock()
    mock_client.credit_notes.list = mock.MagicMock()

    with (
        mock.patch("posthog.temporal.data_imports.sources.stripe.stripe.StripeClient", return_value=mock_client),
        pytest.raises(StripeValidationError) as e,
    ):
        validate_credentials("api_key")

    assert list(e.value.errors.keys()) == ["Charge"]
    assert list(e.value.missing_permissions.keys()) == ["Subscription"]


@pytest.mark.parametrize(
    "nested_table_name",
    [CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME, CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME],
)
def test_validate_credentials_nested_resource_validates_via_parent(nested_table_name):
    """Nested resources can't be listed without a parent customer ID. Validating them
    must proxy to the Customer endpoint instead of raising a fake "<resource> does not exist"
    error — which used to surface as "Stripe credentials lack permissions for CustomerPaymentMethod"
    every time the user toggled the sync method on a nested table."""
    mock_client = mock.MagicMock()
    mock_client.customers.list = mock.MagicMock()

    with mock.patch("posthog.temporal.data_imports.sources.stripe.stripe.StripeClient", return_value=mock_client):
        result = validate_credentials("api_key", nested_table_name)

    assert result is True
    # The parent's list endpoint is the one we actually call.
    mock_client.customers.list.assert_called_once_with(params={"limit": 1})


@pytest.mark.parametrize(
    "nested_table_name",
    [CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME, CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME],
)
def test_validate_credentials_nested_resource_surfaces_parent_permission_error(nested_table_name):
    """If the parent (Customer) scope is missing, the error must name both the nested table
    the user toggled and the parent that actually gates the permission — `Nested (Parent)` —
    so the message is unambiguous about which Stripe scope to grant."""
    mock_client = mock.MagicMock()
    mock_client.customers.list = mock.MagicMock(side_effect=stripe_lib.PermissionError(message="Forbidden"))

    with (
        mock.patch("posthog.temporal.data_imports.sources.stripe.stripe.StripeClient", return_value=mock_client),
        pytest.raises(StripePermissionError) as e,
    ):
        validate_credentials("api_key", nested_table_name)

    assert list(e.value.missing_permissions.keys()) == [f"{nested_table_name} (Customer)"]


def test_clean_stripe_error_message_collapses_redacted_key():
    """Stripe's permission errors quote the restricted key with ~80 redacted middle chars
    (`rk_live_***********...***********gbeftZ`). The unedited message is too long for a
    toast — collapse the asterisk run while keeping the visible prefix/suffix that lets
    users identify which key was used."""
    raw = (
        "Request req_DzMMiyPa4cynLi: The provided key 'rk_live_"
        + ("*" * 80)
        + "gbeftZ' does not have the required permissions for this endpoint on account "
        + "'acct_1HIMDDEuIatRXSdz'. Having the 'rak_payment_method_read' permission would "
        + "allow this request to continue."
    )

    cleaned = _clean_stripe_error_message(raw)

    assert "*" * 80 not in cleaned
    assert "***" in cleaned  # we keep a short marker
    assert "rk_live_***gbeftZ" in cleaned
    # Critically, the actionable detail must survive the cleanup.
    assert "rak_payment_method_read" in cleaned


def test_clean_stripe_error_message_passthrough_when_no_redaction():
    """No redacted run in the message → return unchanged."""
    msg = "Request req_xxx: Some non-permission error without redaction."
    assert _clean_stripe_error_message(msg) == msg


def test_validate_credentials_nested_resources_have_registered_parents():
    """Invariant: every StripeNestedResource's `parent_name` must point at a key that is
    also registered as a top-level StripeResource in _build_resources. validate_credentials
    does a direct dict lookup on parent_name, so a miss would crash rather than render a
    useful error. Catch the misconfiguration here in CI rather than at runtime.

    Important: this test does NOT compare method identity. Stripe's SDK exposes endpoints
    via property descriptors that return a fresh bound method on every attribute access
    (`id(client.customers.list) == id(client.customers.list)` is False). MagicMock caches
    attribute access and made identity checks falsely pass — so the linkage is carried
    explicitly via the `parent_name` string instead.
    """
    mock_client = mock.MagicMock()
    resources = _build_resources(mock_client, logger=None)

    for name, resource in resources.items():
        if isinstance(resource, StripeNestedResource):
            assert resource.parent_name, f"Nested resource {name!r} must declare a parent_name."
            parent_entry = resources.get(resource.parent_name)
            assert isinstance(parent_entry, StripeResource), (
                f"Nested resource {name!r} declares parent_name={resource.parent_name!r}, but no "
                f"top-level StripeResource with that name is registered in _build_resources. "
                f"validate_credentials would crash trying to resolve it."
            )


def test_validate_credentials_with_missing_table_name():
    mock_client = mock.MagicMock()

    # Mock each resource's list method
    mock_client.accounts.list = mock.MagicMock()
    mock_client.balance_transactions.list = mock.MagicMock()
    mock_client.charges.list = mock.MagicMock()
    mock_client.customers.list = mock.MagicMock()
    mock_client.disputes.list = mock.MagicMock()
    mock_client.invoice_items.list = mock.MagicMock()
    mock_client.invoices.list = mock.MagicMock()
    mock_client.payouts.list = mock.MagicMock()
    mock_client.prices.list = mock.MagicMock()
    mock_client.products.list = mock.MagicMock()
    mock_client.subscriptions.list = mock.MagicMock()
    mock_client.refunds.list = mock.MagicMock()
    mock_client.credit_notes.list = mock.MagicMock()

    with (
        mock.patch("posthog.temporal.data_imports.sources.stripe.stripe.StripeClient", return_value=mock_client),
        pytest.raises(StripePermissionError) as e,
    ):
        validate_credentials("api_key", "bad_table")

    # No endpoint should be called
    mock_client.accounts.list.assert_not_called()
    mock_client.balance_transactions.list.assert_not_called()
    mock_client.charges.list.assert_not_called()
    mock_client.customers.list.assert_not_called()
    mock_client.disputes.list.assert_not_called()
    mock_client.invoice_items.list.assert_not_called()
    mock_client.invoices.list.assert_not_called()
    mock_client.payouts.list.assert_not_called()
    mock_client.prices.list.assert_not_called()
    mock_client.products.list.assert_not_called()
    mock_client.subscriptions.list.assert_not_called()
    mock_client.refunds.list.assert_not_called()
    mock_client.credit_notes.list.assert_not_called()

    assert "bad_table" in str(e)


class TestGetApiKey:
    @pytest.fixture
    def stripe_source(self):
        return StripeSource()

    @pytest.fixture
    def stripe_integration(self, team):
        return Integration.objects.create(
            team=team,
            kind="stripe",
            config={"account_name": "Test Business (acct_123)"},
            sensitive_config={"access_token": "sk_live_oauth_token"},
            integration_id="acct_123",
        )

    def test_api_key_selection_returns_key(self, stripe_source):
        config = StripeSourceConfig.from_dict(
            {"auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"}}
        )
        assert stripe_source._get_api_key(config, team_id=1) == "sk_test_123"

    def test_api_key_selection_raises_when_key_missing(self, stripe_source):
        config = StripeSourceConfig.from_dict({"auth_method": {"selection": "api_key"}})
        with pytest.raises(ValueError, match="Missing Stripe API key"):
            stripe_source._get_api_key(config, team_id=1)

    @pytest.mark.django_db
    def test_oauth_selection_returns_access_token(self, stripe_source, team, stripe_integration):
        config = StripeSourceConfig.from_dict(
            {"auth_method": {"selection": "oauth", "stripe_integration_id": stripe_integration.id}}
        )
        assert stripe_source._get_api_key(config, team.pk) == "sk_live_oauth_token"

    def test_oauth_selection_raises_when_integration_id_missing(self, stripe_source):
        config = StripeSourceConfig.from_dict({"auth_method": {"selection": "oauth"}})
        with pytest.raises(ValueError, match="Missing Stripe integration ID"):
            stripe_source._get_api_key(config, team_id=1)

    @pytest.mark.django_db
    def test_oauth_selection_raises_when_integration_not_found(self, stripe_source, team):
        config = StripeSourceConfig.from_dict({"auth_method": {"selection": "oauth", "stripe_integration_id": 99999}})
        with pytest.raises(ValueError, match="Integration not found"):
            stripe_source._get_api_key(config, team.pk)
