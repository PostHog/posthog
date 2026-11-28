"""Test module covering utilities used for batch exporting to BigQuery."""

import os
import uuid
import datetime as dt
from collections.abc import AsyncIterator

import pytest
from unittest.mock import DEFAULT, AsyncMock, MagicMock, patch

from django.test import override_settings

import pyarrow as pa
import pyarrow.parquet as pq
from google.api_core.exceptions import DeadlineExceeded, ServiceUnavailable
from google.auth.exceptions import RefreshError
from google.cloud import bigquery, iam_admin_v1

from posthog.models.integration import GoogleCloudServiceAccountIntegration

from products.batch_exports.backend.temporal.destinations.bigquery_batch_export import (
    BigQueryField,
    BigQueryInsertInputs,
    BigQueryIntegrationNotFoundError,
    BigQueryTable,
    Boto3CredentialsSupplier,
    GoogleCloudCredentialsError,
    ServiceAccountOwnershipError,
    _make_parquet_pipeline_transformer,
    ensure_our_google_cloud_credentials_are_valid,
    get_our_google_cloud_credentials,
    get_service_account_description,
    insert_into_bigquery_activity_from_stage,
    verify_impersonated_service_account_ownership,
)
from products.batch_exports.backend.tests.temporal.destinations.bigquery.utils import (
    SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS,
)


@pytest.mark.parametrize(
    "pyrecords,expected_schema",
    [
        ([{"test": 1}], [bigquery.SchemaField("test", "INT64")]),
        ([{"test": "a string"}], [bigquery.SchemaField("test", "STRING")]),
        ([{"test": b"a bytes"}], [bigquery.SchemaField("test", "BYTES")]),
        ([{"test": 6.0}], [bigquery.SchemaField("test", "FLOAT64")]),
        ([{"test": True}], [bigquery.SchemaField("test", "BOOL")]),
        ([{"test": dt.datetime.now()}], [bigquery.SchemaField("test", "TIMESTAMP")]),
        ([{"test": dt.datetime.now(tz=dt.UTC)}], [bigquery.SchemaField("test", "TIMESTAMP")]),
        (
            [
                {
                    "test_int": 1,
                    "test_str": "a string",
                    "test_bytes": b"a bytes",
                    "test_float": 6.0,
                    "test_bool": False,
                    "test_timestamp": dt.datetime.now(),
                    "test_timestamptz": dt.datetime.now(tz=dt.UTC),
                }
            ],
            [
                bigquery.SchemaField("test_int", "INT64"),
                bigquery.SchemaField("test_str", "STRING"),
                bigquery.SchemaField("test_bytes", "BYTES"),
                bigquery.SchemaField("test_float", "FLOAT64"),
                bigquery.SchemaField("test_bool", "BOOL"),
                bigquery.SchemaField("test_timestamp", "TIMESTAMP"),
                bigquery.SchemaField("test_timestamptz", "TIMESTAMP"),
            ],
        ),
    ],
)
def test_field_resolves_to_bigquery_schema_field(pyrecords, expected_schema):
    """Test BigQuery schema fields generated with BigQueryField match expected."""
    record_batch = pa.RecordBatch.from_pylist(pyrecords)

    schema = []
    for column in record_batch.schema:
        field = BigQueryField.from_arrow_field(column)
        schema.append(field.to_destination_field())

    assert schema == expected_schema


@pytest.mark.parametrize(
    "model_name,expected",
    [
        (
            "persons",
            pa.array(
                [dt.datetime(2025, 1, 1, tzinfo=dt.UTC), dt.datetime(2106, 2, 7, 6, 28, 15, tzinfo=dt.UTC), None],
                type=pa.timestamp("us", tz="UTC"),
            ),
        ),
        ("hogql", pa.array([1_735_689_600, 2**32 - 1, None], type=pa.uint32())),
    ],
)
async def test_bigquery_parquet_coerces_epoch_seconds_only_for_persons(model_name: str, expected: pa.Array) -> None:
    table = BigQueryTable.from_bigquery_table(
        bigquery.Table("project.dataset.destination", schema=[bigquery.SchemaField("created_at", "TIMESTAMP")])
    )
    transformer = _make_parquet_pipeline_transformer(table, max_file_size_bytes=0, model_name=model_name)

    async def batches() -> AsyncIterator[pa.RecordBatch]:
        yield pa.record_batch({"created_at": pa.array([1_735_689_600, 2**32 - 1, None], type=pa.uint32())})

    parquet_data = b"".join([chunk.data async for chunk in transformer.iter(batches())])
    parquet_file = pq.ParquetFile(pa.BufferReader(parquet_data))
    assert parquet_file.schema.column(0).converted_type == (
        "TIMESTAMP_MICROS" if model_name == "persons" else "UINT_32"
    )
    assert parquet_file.read()["created_at"].combine_chunks() == expected


async def test_boto3_credentials_supplier_get_aws_region():
    """Assert credentials supplier gets region from environment."""
    supplier = Boto3CredentialsSupplier()
    region_name = "something"

    with patch.dict(os.environ, {"AWS_DEFAULT_REGION": region_name}):
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

    with pytest.raises(RefreshError):
        _ = supplier.get_aws_security_credentials(None, None)


@SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS
@pytest.mark.asyncio
@pytest.mark.parametrize("integration", ["impersonated"], indirect=True)
@pytest.mark.parametrize("service_account_description", ["any"], indirect=True)
async def test_get_service_account_description(
    aorganization,
    integration,
    service_account_description,
):
    """Test can get a service account's description."""
    service_account_integration = GoogleCloudServiceAccountIntegration(integration)
    description = await get_service_account_description(service_account_integration.service_account_email)

    assert description == service_account_description


@SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS
@pytest.mark.asyncio
@pytest.mark.parametrize("integration", ["impersonated"], indirect=True)
@pytest.mark.parametrize("service_account_description", ["any"], indirect=True)
async def test_get_service_account_description_retries(
    aorganization,
    integration,
    service_account_description,
) -> None:
    service_account_integration = GoogleCloudServiceAccountIntegration(integration)
    async with iam_admin_v1.IAMAsyncClient(credentials=get_our_google_cloud_credentials()) as client:
        with (
            patch.object(
                iam_admin_v1.IAMAsyncClient,
                "get_service_account",
                wraps=client.get_service_account,
                side_effect=[DeadlineExceeded("Deadline exceeded"), ServiceUnavailable("Unavailable"), DEFAULT],
            ) as get_service_account,
            patch("products.batch_exports.backend.temporal.utils.asyncio.sleep", new_callable=AsyncMock),
        ):
            description = await get_service_account_description(service_account_integration.service_account_email)

    assert description == service_account_description
    assert get_service_account.await_count == 3


@SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS
@pytest.mark.asyncio
@pytest.mark.parametrize("integration", ["impersonated"], indirect=True)
async def test_verify_impersonated_service_account_ownership(
    aorganization,
    ateam,
    integration,
    service_account_description,
):
    """Test verifying ownership of impersonated service account does not fail."""
    service_account_integration = GoogleCloudServiceAccountIntegration(integration)
    await verify_impersonated_service_account_ownership(service_account_integration.service_account_email, ateam.id)


@SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS
@pytest.mark.asyncio
@pytest.mark.parametrize("integration", ["impersonated"], indirect=True)
@pytest.mark.parametrize("service_account_description", ["any"], indirect=True)
async def test_verify_impersonated_service_account_ownership_raises(
    aorganization,
    ateam,
    integration,
    service_account_description,
):
    """Test verifying ownership of impersonated service account fails when description is set to 'any'."""
    service_account_integration = GoogleCloudServiceAccountIntegration(integration)
    with pytest.raises(ServiceAccountOwnershipError) as excinfo:
        await verify_impersonated_service_account_ownership(
            service_account_integration.service_account_email, ateam.id, max_attempts=1
        )

    assert f"posthog:{str(aorganization.id)}" in str(excinfo.value)


@pytest.mark.asyncio
async def test_ensure_our_google_cloud_credentials_are_valid():
    """Test ensuring our credentials are valid will raise when they are not."""
    with override_settings(BATCH_EXPORT_BIGQUERY_SERVICE_ACCOUNT="garbage"):
        with pytest.raises(GoogleCloudCredentialsError):
            await ensure_our_google_cloud_credentials_are_valid()


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_insert_activity_fails_when_export_has_no_integration(activity_environment):
    inputs = BigQueryInsertInputs(
        team_id=1,
        batch_export_id=str(uuid.uuid4()),
        data_interval_start="2023-12-31T23:00:00+00:00",
        data_interval_end="2024-01-01T00:00:00+00:00",
        dataset_id="dataset",
        table_id="events",
    )

    result = await activity_environment.run(insert_into_bigquery_activity_from_stage, inputs)

    assert result.error is not None
    assert result.error.type == BigQueryIntegrationNotFoundError.__name__
