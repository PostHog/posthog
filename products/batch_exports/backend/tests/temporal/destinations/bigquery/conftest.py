import os
import json
import uuid
import typing
import warnings

import pytest

import pytest_asyncio
from google.cloud import bigquery

from posthog.models.integration import Integration

from products.batch_exports.backend.tests.temporal.destinations.s3.utils import (
    has_valid_credentials as has_valid_aws_credentials,
)


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


async def key_file_integration(ateam, bigquery_config):
    integration = await Integration.objects.acreate(
        team_id=ateam.pk,
        kind=Integration.IntegrationKind.GOOGLE_CLOUD_SERVICE_ACCOUNT,
        integration_id=f"{ateam.id}-{bigquery_config['client_email']}",
        config={
            "project_id": bigquery_config["project_id"],
            "service_account_email": bigquery_config["client_email"],
        },
        sensitive_config={
            "private_key": bigquery_config["private_key"],
            "private_key_id": bigquery_config["private_key_id"],
            "token_uri": bigquery_config["token_uri"],
        },
    )
    return integration


async def impersonated_integration(ateam, bigquery_config):
    """Configure integration to impersonate our test service account.

    This requires the `BATCH_EXPORT_BIGQUERY_SERVICE_ACCOUNT` setting to be set, as
    that's the original service account that will be assumed to do the impersonation.
    """
    integration = await Integration.objects.acreate(
        team_id=ateam.pk,
        kind=Integration.IntegrationKind.GOOGLE_CLOUD_SERVICE_ACCOUNT,
        integration_id=f"{ateam.id}-{bigquery_config['client_email']}",
        config={
            "project_id": bigquery_config["project_id"],
            "service_account_email": bigquery_config["client_email"],
        },
    )
    return integration


@pytest_asyncio.fixture
async def integration(request, ateam, bigquery_config) -> None | Integration:
    try:
        integration_type = request.param
    except Exception:
        return None

    match integration_type:
        case "impersonated":
            if not has_valid_aws_credentials():
                pytest.skip("AWS credentials not available")

            integration = await impersonated_integration(ateam, bigquery_config)
        case "key_file":
            integration = await key_file_integration(ateam, bigquery_config)
        case _:
            integration = None

    return integration


@pytest.fixture
def use_json_type(request) -> bool:
    """A parametrizable fixture to configure the bool use_json_type setting."""
    try:
        return request.param
    except AttributeError:
        return False
