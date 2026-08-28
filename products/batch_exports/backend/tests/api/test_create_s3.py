import pytest

from django.test.client import Client as HttpClient

from rest_framework import status
from temporalio.client import ScheduleActionStartWorkflow

from products.batch_exports.backend.tests.api.conftest import describe_schedule
from products.batch_exports.backend.tests.api.operations import create_batch_export

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("temporal_worker", "cleanup"),
]

_S3_FAMILY_TYPES = ["AwsS3", "S3Compatible"]

_S3_FAMILY_BASE_CONFIG = {
    "bucket_name": "my-bucket",
    "region": "us-east-1",
    "prefix": "events/",
}


@pytest.mark.parametrize(
    "destination_type,integration_fixture,extra_config,expected_persisted_type",
    [
        # Refined AwsS3 (with AWS-only encryption field)
        ("AwsS3", "aws_s3_integration", {"encryption": "AES256"}, "AwsS3"),
        # Refined S3Compatible (with its addressing-style field)
        ("S3Compatible", "s3_compatible_integration", {"use_virtual_style_addressing": True}, "S3Compatible"),
    ],
)
def test_create_s3_family_batch_export(
    client: HttpClient,
    temporal,
    organization,
    team,
    user,
    destination_type,
    integration_fixture,
    extra_config,
    expected_persisted_type,
    request,
):
    """Posting a creatable S3-family destination type creates a batch export and persists with the expected type."""
    integration = request.getfixturevalue(integration_fixture)
    client.force_login(user)
    response = create_batch_export(
        client,
        team.pk,
        {
            "name": "my-export",
            "interval": "hour",
            "destination": {
                "type": destination_type,
                "config": {**_S3_FAMILY_BASE_CONFIG, **extra_config},
                "integration": integration.id,
            },
        },
    )
    assert response.status_code == status.HTTP_201_CREATED, response.json()
    assert response.json()["destination"]["type"] == expected_persisted_type


@pytest.mark.parametrize("destination_type", _S3_FAMILY_TYPES)
def test_create_s3_family_batch_export_requires_an_integration(
    client: HttpClient, temporal, organization, team, user, destination_type
):
    """An S3-family export cannot be created without an Integration to authenticate through."""
    client.force_login(user)
    response = create_batch_export(
        client,
        team.pk,
        {
            "name": "my-export",
            "interval": "hour",
            "destination": {"type": destination_type, "config": {**_S3_FAMILY_BASE_CONFIG}},
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert response.json()["detail"] == f"Integration is required for {destination_type} batch exports"


def test_create_legacy_s3_type_is_rejected(client: HttpClient, temporal, organization, team, user):
    """The legacy `S3` type is deprecated and can no longer be created via the API."""
    client.force_login(user)
    response = create_batch_export(
        client,
        team.pk,
        {
            "name": "my-export",
            "interval": "hour",
            "destination": {"type": "S3", "config": {**_S3_FAMILY_BASE_CONFIG}},
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert "deprecated" in response.json()["detail"]
    assert "AwsS3" in response.json()["detail"]
    assert "S3Compatible" in response.json()["detail"]


@pytest.mark.parametrize(
    "destination_type,integration_fixture",
    [
        ("AwsS3", "aws_s3_integration"),
        ("S3Compatible", "s3_compatible_integration"),
    ],
)
def test_create_s3_family_batch_export_validates_empty_inputs(
    client: HttpClient, temporal, organization, team, user, destination_type, integration_fixture, request
):
    """Empty required string inputs are rejected for every S3-family destination.

    Credentials come from the integration, so the bucket/region/prefix inputs are the ones
    that can still arrive empty.
    """
    integration = request.getfixturevalue(integration_fixture)
    client.force_login(user)
    config = {**_S3_FAMILY_BASE_CONFIG, "bucket_name": "", "region": ""}

    response = create_batch_export(
        client,
        team.pk,
        {
            "name": "my-export",
            "interval": "hour",
            "destination": {"type": destination_type, "config": config, "integration": integration.id},
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["detail"] == "The following inputs are empty: ['bucket_name', 'region']"


@pytest.mark.parametrize(
    "destination_type,integration_fixture,credential_field",
    [
        ("AwsS3", "aws_s3_integration", "aws_access_key_id"),
        ("AwsS3", "aws_s3_integration", "aws_secret_access_key"),
        ("S3Compatible", "s3_compatible_integration", "aws_access_key_id"),
        ("S3Compatible", "s3_compatible_integration", "aws_secret_access_key"),
        # `endpoint_url` is an S3Compatible-only field; AwsS3 rejects it as unknown instead.
        ("S3Compatible", "s3_compatible_integration", "endpoint_url"),
    ],
)
def test_create_s3_family_batch_export_rejects_inline_credentials(
    client: HttpClient,
    temporal,
    organization,
    team,
    user,
    destination_type,
    integration_fixture,
    credential_field,
    request,
):
    """Credentials and the provider endpoint belong to the integration, so config may not carry them.

    An accepted value here would be persisted in `config` and copied into the export's Temporal
    schedule arguments.
    """
    integration = request.getfixturevalue(integration_fixture)
    client.force_login(user)
    response = create_batch_export(
        client,
        team.pk,
        {
            "name": "my-export",
            "interval": "hour",
            "destination": {
                "type": destination_type,
                "config": {**_S3_FAMILY_BASE_CONFIG, credential_field: "https://localhost:9000"},
                "integration": integration.id,
            },
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert response.json()["detail"] == (
        f"{destination_type} batch exports authenticate through their integration. "
        f"Remove these fields from the configuration: ['{credential_field}']"
    )


@pytest.mark.parametrize(
    "destination_type,extra_config,offending_field",
    [
        # AwsS3 rejects S3-compatible-only fields.
        ("AwsS3", {"endpoint_url": "https://localhost:9000"}, "endpoint_url"),
        ("AwsS3", {"use_virtual_style_addressing": True}, "use_virtual_style_addressing"),
        # S3Compatible rejects AWS-only fields.
        ("S3Compatible", {"endpoint_url": "https://localhost:9000", "kms_key_id": "alias/test"}, "kms_key_id"),
        ("S3Compatible", {"endpoint_url": "https://localhost:9000", "encryption": "aws:kms"}, "encryption"),
    ],
)
def test_create_s3_family_batch_export_rejects_inapplicable_fields(
    client: HttpClient,
    temporal,
    organization,
    team,
    user,
    destination_type,
    extra_config,
    offending_field,
):
    """Strict per-destination validation rejects fields that don't belong to the destination."""
    client.force_login(user)
    response = create_batch_export(
        client,
        team.pk,
        {
            "name": "my-export",
            "interval": "hour",
            "destination": {
                "type": destination_type,
                "config": {**_S3_FAMILY_BASE_CONFIG, **extra_config},
            },
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert offending_field in response.json()["detail"]


@pytest.mark.parametrize(
    "file_format,compression,expected_error_message",
    [
        ("JSONLines", None, None),
        ("JSONLines", "gzip", None),
        (
            "JSONLines",
            "zstd",
            "Compression zstd is not supported for file format JSONLines. Supported compressions are ['gzip', 'brotli']",
        ),
        ("Parquet", None, None),
        ("Parquet", "gzip", None),
        ("Parquet", "brotli", None),
        ("Parquet", "zstd", None),
        (
            "Parquet",
            "unknown",
            "Compression unknown is not supported for file format Parquet. Supported compressions are ['zstd', 'lz4', 'snappy', 'gzip', 'brotli']",
        ),
        (
            "unknown",
            "gzip",
            "File format unknown is not supported. Supported file formats are ['Parquet', 'JSONLines']",
        ),
    ],
)
def test_create_s3_batch_export_validates_file_format_and_compression(
    client: HttpClient,
    file_format,
    compression,
    expected_error_message,
    temporal,
    organization,
    team,
    user,
    aws_s3_integration,
):
    """Test creating a BatchExport with S3 destination validates file format and compression."""

    destination_data = {
        "type": "AwsS3",
        "integration": aws_s3_integration.id,
        "config": {
            "bucket_name": "my-s3-bucket",
            "region": "us-east-1",
            "prefix": "posthog-events/",
            "file_format": file_format,
            "compression": compression,
        },
    }

    batch_export_data = {
        "name": "my-s3-bucket",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)

    response = create_batch_export(
        client,
        team.pk,
        batch_export_data,
    )

    if expected_error_message is None:
        assert response.status_code == status.HTTP_201_CREATED
    else:
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == expected_error_message


# The endpoint URL now lives on the s3-compatible integration, which SSRF-checks it on creation
# (see `test_create_rejects_invalid_endpoint_url` in posthog/api/test/test_integration.py).


@pytest.mark.parametrize(
    "destination_type,integration_fixture",
    [
        ("AwsS3", "aws_s3_integration"),
        ("S3Compatible", "s3_compatible_integration"),
    ],
)
def test_create_s3_family_batch_export_using_integration(
    client: HttpClient, temporal, organization, team, user, destination_type, integration_fixture, request
):
    """An S3-family export authenticates via a matching integration, with no inline credentials in config."""
    integration = request.getfixturevalue(integration_fixture)
    client.force_login(user)
    response = create_batch_export(
        client,
        team.pk,
        {
            "name": "my-export",
            "interval": "hour",
            "destination": {
                "type": destination_type,
                # No credentials (nor endpoint_url) inline — they come from the integration.
                "config": {"bucket_name": "my-bucket", "region": "us-east-1", "prefix": "events/"},
                "integration": integration.id,
            },
        },
    )
    assert response.status_code == status.HTTP_201_CREATED, response.json()
    data = response.json()
    assert data["destination"]["type"] == destination_type
    assert "aws_access_key_id" not in data["destination"]["config"]
    assert "aws_secret_access_key" not in data["destination"]["config"]

    schedule = describe_schedule(temporal, data["id"])
    assert isinstance(schedule.schedule.action, ScheduleActionStartWorkflow)
    assert schedule.schedule.action.workflow == "s3-export"


@pytest.mark.parametrize(
    "destination_type,integration_fixture",
    [
        ("AwsS3", "s3_compatible_integration"),
        ("S3Compatible", "aws_s3_integration"),
    ],
)
def test_create_s3_family_batch_export_rejects_mismatched_integration_kind(
    client: HttpClient, temporal, organization, team, user, destination_type, integration_fixture, request
):
    """An S3-family export rejects an integration whose kind doesn't match the destination type."""
    integration = request.getfixturevalue(integration_fixture)
    client.force_login(user)
    response = create_batch_export(
        client,
        team.pk,
        {
            "name": "my-export",
            "interval": "hour",
            "destination": {
                "type": destination_type,
                "config": {"bucket_name": "my-bucket", "region": "us-east-1", "prefix": "events/"},
                "integration": integration.id,
            },
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
