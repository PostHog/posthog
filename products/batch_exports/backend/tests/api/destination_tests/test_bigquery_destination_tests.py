import os
import json
import uuid
import typing
import warnings

import pytest

from google.cloud import bigquery, exceptions

from products.batch_exports.backend.api.destination_tests.bigquery import (
    BigQueryDatasetTestStep,
    BigQueryProjectTestStep,
    BigQueryTableTestStep,
    Status,
)

SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS = pytest.mark.skipif(
    "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ,
    reason="Google credentials not set in environment",
)

pytestmark = [SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS, pytest.mark.asyncio]


@pytest.fixture
def bigquery_config() -> dict[str, str]:
    """Return a BigQuery configuration dictionary to use in tests."""
    credentials_file_path = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    with open(credentials_file_path) as f:
        credentials = json.load(f)

    return {
        "project_id": credentials["project_id"],
        "private_key": credentials["private_key"],
        "private_key_id": credentials["private_key_id"],
        "token_uri": credentials["token_uri"],
        "client_email": credentials["client_email"],
    }


@pytest.fixture
def bigquery_client() -> typing.Generator[bigquery.Client, None, None]:
    """Manage a bigquery.Client for testing."""
    client = bigquery.Client()

    yield client

    client.close()


@pytest.fixture
def bigquery_dataset(bigquery_config, bigquery_client) -> typing.Generator[bigquery.Dataset, None, None]:
    """Manage a bigquery dataset for testing.

    We clean up the dataset after every test. Could be quite time expensive, but guarantees a clean slate.
    """
    dataset_id = f"{bigquery_config['project_id']}.BatchExportsTest_{str(uuid.uuid4()).replace('-', '')}"

    dataset = bigquery.Dataset(dataset_id)
    dataset = bigquery_client.create_dataset(dataset)

    yield dataset

    try:
        bigquery_client.delete_dataset(dataset_id, delete_contents=True, not_found_ok=True)
    except Exception as exc:
        warnings.warn(
            f"Failed to clean up dataset: {dataset_id} due to '{exc.__class__.__name__}': {str(exc)}", stacklevel=1
        )


@pytest.fixture
def project_id(bigquery_config):
    return bigquery_config["project_id"]


@pytest.fixture
def service_account_info(bigquery_config):
    return {k: v for k, v in bigquery_config.items() if k != "project_id"}


async def test_bigquery_check_dataset_exists_test_step(project_id, service_account_info, bigquery_dataset):
    test_step = BigQueryDatasetTestStep(
        project_id=project_id,
        dataset_id=bigquery_dataset.dataset_id,
        service_account_info=service_account_info,
    )
    result = await test_step.run()

    assert result.status == Status.PASSED
    assert result.message is None


async def test_bigquery_check_dataset_exists_test_step_without_dataset(project_id, service_account_info):
    test_step = BigQueryDatasetTestStep(
        project_id=project_id,
        dataset_id="garbage",
        service_account_info=service_account_info,
    )
    result = await test_step.run()

    assert result.status == Status.FAILED
    assert (
        result.message
        == "Dataset 'garbage' could not be found because it doesn't exist or we don't have permissions to use it"
    )


async def test_bigquery_check_project_exists_test_step(project_id, service_account_info):
    test_step = BigQueryProjectTestStep(
        project_id=project_id,
        service_account_info=service_account_info,
    )
    result = await test_step.run()

    assert result.status == Status.PASSED
    assert result.message is None


async def test_bigquery_check_project_exists_test_step_without_project(service_account_info):
    test_step = BigQueryProjectTestStep(
        project_id="garbage",
        service_account_info=service_account_info,
    )
    result = await test_step.run()

    assert result.status == Status.FAILED
    assert (
        result.message
        == "Project 'garbage' could not be found because it doesn't exist or we don't have permissions to use it"
    )


async def test_bigquery_check_table_test_step(project_id, bigquery_client, bigquery_dataset, service_account_info):
    table_id = f"destination_test_{uuid.uuid4()}"
    fully_qualified_table_id = f"{project_id}.{bigquery_dataset.dataset_id}.{table_id}"

    with pytest.raises(exceptions.NotFound):
        bigquery_client.get_table(fully_qualified_table_id)

    test_step = BigQueryTableTestStep(
        project_id=project_id,
        dataset_id=bigquery_dataset.dataset_id,
        table_id=table_id,
        service_account_info=service_account_info,
    )
    result = await test_step.run()

    assert result.status == Status.PASSED
    assert result.message is None

    with pytest.raises(exceptions.NotFound):
        bigquery_client.get_table(fully_qualified_table_id)


async def test_bigquery_check_table_test_step_with_invalid_identifier(
    project_id, bigquery_client, bigquery_dataset, service_account_info
):
    table_id = f"$destination_test_{uuid.uuid4()}"
    fully_qualified_table_id = f"{project_id}.{bigquery_dataset.dataset_id}.{table_id}"

    with pytest.raises(exceptions.NotFound):
        bigquery_client.get_table(fully_qualified_table_id)

    test_step = BigQueryTableTestStep(
        project_id=project_id,
        dataset_id=bigquery_dataset.dataset_id,
        table_id=table_id,
        service_account_info=service_account_info,
    )
    result = await test_step.run()

    assert result.status == Status.FAILED
    assert result.message is not None
    assert result.message.startswith(f"A table could not be created in dataset '{bigquery_dataset.dataset_id}'")

    with pytest.raises(exceptions.NotFound):
        bigquery_client.get_table(fully_qualified_table_id)


@pytest.mark.parametrize("step", [BigQueryTableTestStep(), BigQueryProjectTestStep(), BigQueryDatasetTestStep()])
async def test_test_steps_fail_if_not_configured(step):
    result = await step.run()
    assert result.status == Status.FAILED
    assert result.message == "The test step cannot run as it's not configured."
