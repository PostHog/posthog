import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.stripe.constants import ACCOUNT_RESOURCE_NAME
from posthog.temporal.data_imports.sources.stripe.stripe import (
    StripePermissionError,
    StripeResumeConfig,
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
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
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
