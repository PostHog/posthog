import os
import json
import uuid
import typing
import warnings

import pytest

from google.cloud import bigquery


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
def use_json_type(request) -> bool:
    """A parametrizable fixture to configure the bool use_json_type setting."""
    try:
        return request.param
    except AttributeError:
        return False
