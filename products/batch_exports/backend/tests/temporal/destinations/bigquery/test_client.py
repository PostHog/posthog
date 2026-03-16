import os
import random
import string

import pytest
from unittest.mock import MagicMock, patch

from google.cloud import bigquery

from products.batch_exports.backend.temporal.destinations.bigquery_batch_export import (
    AWSCredentialsMissingError,
    BigQueryClient,
    BigQueryField,
    BigQueryTable,
    BigQueryType,
    Boto3CredentialsSupplier,
    GoogleCloudServiceAccountIntegration,
    StartQueryTimeoutError,
)
from products.batch_exports.backend.tests.temporal.destinations.bigquery.utils import (
    SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS,
)
from products.batch_exports.backend.tests.temporal.destinations.s3.utils import (
    has_valid_credentials as has_valid_aws_credentials,
)


@pytest.mark.parametrize(
    "states_sequence,should_timeout",
    [
        (["PENDING", "PENDING", "RUNNING", "DONE"], False),
        (["PENDING"] * 100, True),
        (["RUNNING", "DONE"], False),
    ],
    ids=["eventually_starts", "stays_pending_times_out", "starts_immediately"],
)
@pytest.mark.asyncio
async def test_execute_query_pending_timeout(states_sequence: list[str], should_timeout: bool):
    mock_query_job = MagicMock()
    state_iter = iter(states_sequence)
    mock_query_job.state = next(state_iter)
    mock_query_job.job_id = "test-job-id"

    def reload_side_effect():
        try:
            mock_query_job.state = next(state_iter)
        except StopIteration:
            pass

    mock_query_job.reload = reload_side_effect
    mock_result = MagicMock(name="mock_result")
    mock_query_job.result.return_value = mock_result

    mock_sync_client = MagicMock()
    mock_sync_client.query.return_value = mock_query_job
    mock_sync_client.project = "test-project"

    client = BigQueryClient(mock_sync_client)

    if should_timeout:
        with pytest.raises(
            StartQueryTimeoutError, match="Query still in 'PENDING' state after 0.05 seconds; timing out."
        ):
            await client.execute_query(
                "SELECT 1",
                start_query_timeout=0.05,
                poll_interval=0.01,
            )
        mock_query_job.cancel.assert_called_once()
    else:
        result = await client.execute_query(
            "SELECT 1",
            start_query_timeout=0.5,
            poll_interval=0.01,
        )
        assert result == mock_result


@SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fields,time_partitioning",
    [
        [(BigQueryField("id", BigQueryType("INT64", False), False),), None],
        [
            (
                BigQueryField("id", BigQueryType("INT64", False), False),
                BigQueryField("timestamp", BigQueryType("TIMESTAMP", False), False),
            ),
            bigquery.TimePartitioning(type_=bigquery.TimePartitioningType.DAY, field="timestamp"),
        ],
    ],
)
async def test_create_table(fields, time_partitioning, bigquery_client, bigquery_config, bigquery_dataset):
    """Assert tables are created."""
    table = BigQueryTable(
        f"test_table_{''.join(random.choices(string.ascii_letters, k=10))}",
        fields,
        parents=(bigquery_client.project, bigquery_dataset.dataset_id),
        time_partitioning=time_partitioning,
    )
    client = BigQueryClient(bigquery_client)
    created = await client.create_table(table)

    try:
        assert created.time_partitioning == table.time_partitioning == time_partitioning
        assert all(field.name in created for field in fields)
    finally:
        await client.delete_table(table)


@SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS
@pytest.mark.asyncio
async def test_from_service_account_integration_with_keys(
    key_file_integration,
):
    """Can initialize client from integration produced with key file."""
    client = BigQueryClient.from_service_account_integration(GoogleCloudServiceAccountIntegration(key_file_integration))
    # This triggers a credential refresh, just to make sure it is correctly set up.
    results = list(client.sync_client.query("SELECT 1").result())

    assert results[0].values()[0] == 1


async def test_boto3_credentials_supplier_get_aws_region():
    """Assert credentials supplier gets region from environment."""
    supplier = Boto3CredentialsSupplier()
    region_name = "something"

    with patch.dict(os.environ, {"AWS_REGION": region_name}):
        assert region_name == supplier.get_aws_region(None, None)


@pytest.fixture
def mock_aws_credentials():
    frozen_credentials = MagicMock()
    frozen_credentials.access_key = "access-key"
    frozen_credentials.secret_key = "secret-key"
    frozen_credentials.token = "token"

    session_credentials = MagicMock()
    session_credentials.get_frozen_credentials.return_value = frozen_credentials

    mock_session = MagicMock()
    mock_session.get_credentials.return_value = session_credentials

    return mock_session


def test_boto3_credentials_supplier_mocked_get_aws_security_credentials(mock_aws_credentials):
    """Assert credentials supplier gets mocked AWS credentials."""
    supplier = Boto3CredentialsSupplier(mock_aws_credentials)
    result = supplier.get_aws_security_credentials(None, None)

    assert result.access_key_id == "access-key"
    assert result.secret_access_key == "secret-key"
    assert result.session_token == "token"


def test_boto3_credentials_supplier_raises_if_missing(mock_aws_credentials):
    mock_aws_credentials.get_credentials.return_value = None
    supplier = Boto3CredentialsSupplier(mock_aws_credentials)

    with pytest.raises(AWSCredentialsMissingError):
        _ = supplier.get_aws_security_credentials(None, None)


@SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS
@pytest.mark.skipif(not has_valid_aws_credentials(), reason="AWS credentials not available")
@pytest.mark.asyncio
async def test_from_service_account_integration_with_service_account(
    impersonated_integration,
):
    """Can initialize client from integration configured to impersonate a service account."""
    client = BigQueryClient.from_service_account_integration(
        GoogleCloudServiceAccountIntegration(impersonated_integration)
    )
    # This triggers a credential refresh, just to make sure it is correctly set up.
    results = list(client.sync_client.query("SELECT 1").result())

    assert results[0].values()[0] == 1
