import typing as t

import pytest

from django.test import override_settings
from django.test.client import Client as HttpClient

from rest_framework import status
from temporalio.client import ScheduleActionStartWorkflow

from posthog.models.integration import Integration

from products.batch_exports.backend.models.batch_export import S3_CREATABLE_TYPES
from products.batch_exports.backend.tests.api.conftest import describe_schedule
from products.batch_exports.backend.tests.api.operations import create_batch_export

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("temporal_worker", "cleanup"),
]

_S3_FAMILY_BASE_CONFIG = {
    "bucket_name": "my-bucket",
    "region": "us-east-1",
    "prefix": "events/",
    "aws_access_key_id": "key",
    "aws_secret_access_key": "secret",
}


@pytest.mark.parametrize(
    "destination_type,extra_config,expected_persisted_type",
    [
        # Refined AwsS3 (with AWS-only encryption field)
        ("AwsS3", {"encryption": "AES256"}, "AwsS3"),
        # Refined S3Compatible (endpoint_url is required)
        ("S3Compatible", {"endpoint_url": "https://localhost:9000"}, "S3Compatible"),
    ],
)
def test_create_s3_family_batch_export(
    client: HttpClient,
    temporal,
    organization,
    team,
    user,
    destination_type,
    extra_config,
    expected_persisted_type,
):
    """Posting a creatable S3-family destination type creates a batch export and persists with the expected type."""
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
    assert response.status_code == status.HTTP_201_CREATED, response.json()
    assert response.json()["destination"]["type"] == expected_persisted_type


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


@pytest.mark.parametrize("destination_type", sorted(S3_CREATABLE_TYPES))
def test_create_s3_family_batch_export_validates_empty_inputs(
    client: HttpClient, temporal, organization, team, user, destination_type
):
    """Empty required string inputs are rejected for every S3-family destination."""
    client.force_login(user)
    config = {
        **_S3_FAMILY_BASE_CONFIG,
        "aws_access_key_id": "",
        "aws_secret_access_key": "",
    }
    if destination_type == "S3Compatible":
        # S3Compatible additionally requires `endpoint_url` to be present.
        config["endpoint_url"] = "https://localhost:9000"

    response = create_batch_export(
        client,
        team.pk,
        {
            "name": "my-export",
            "interval": "hour",
            "destination": {"type": destination_type, "config": config},
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["detail"] == "The following inputs are empty: ['aws_access_key_id', 'aws_secret_access_key']"


@pytest.mark.parametrize(
    "destination_type,missing_field",
    [
        *((dt, field) for dt in sorted(S3_CREATABLE_TYPES) for field in ("aws_access_key_id", "aws_secret_access_key")),
        # `endpoint_url` is required only for S3Compatible.
        ("S3Compatible", "endpoint_url"),
    ],
)
def test_create_s3_family_batch_export_validates_missing_required_inputs(
    client: HttpClient,
    temporal,
    organization,
    team,
    user,
    destination_type,
    missing_field,
):
    """Missing required fields are rejected for every S3-family destination."""
    client.force_login(user)
    config = {**_S3_FAMILY_BASE_CONFIG}
    if destination_type == "S3Compatible":
        # S3Compatible requires `endpoint_url` to be present; include it in the
        # base so only `missing_field` is missing after the pop below.
        config["endpoint_url"] = "https://localhost:9000"

    config.pop(missing_field, None)

    response = create_batch_export(
        client,
        team.pk,
        {
            "name": "my-export",
            "interval": "hour",
            "destination": {"type": destination_type, "config": config},
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert f"missing required field: '{missing_field}'" in response.json()["detail"]


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
    client: HttpClient, file_format, compression, expected_error_message, temporal, organization, team, user
):
    """Test creating a BatchExport with S3 destination validates file format and compression."""

    destination_data = {
        "type": "AwsS3",
        "config": {
            "bucket_name": "my-s3-bucket",
            "region": "us-east-1",
            "prefix": "posthog-events/",
            "aws_access_key_id": "abc123",
            "aws_secret_access_key": "secret",
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


@pytest.mark.parametrize(
    "destination_type",
    # Only creatable types that accept `endpoint_url` reach the SSRF check.
    ["S3Compatible"],
)
@pytest.mark.parametrize(
    "endpoint_url",
    [
        "https://192.168.1.1",
        "http://127.0.0.1",
        "http://[::1]/",
        "http://10.0.0.1:9000/",
        "http://169.254.0.0:8080/data",
        "http://localhost",
    ],
)
def test_creating_s3_family_batch_export_fails_if_using_invalid_endpoint_url(
    client: HttpClient, temporal, organization, team, user, destination_type, endpoint_url
):
    """Test that creating an S3 batch export fails if passing an internal IP as endpoint URL.

    Last time I checked, we are not S3.
    """

    destination_data = {
        "type": destination_type,
        "config": {
            **_S3_FAMILY_BASE_CONFIG,
            "use_virtual_style_addressing": True,
            "endpoint_url": endpoint_url,
        },
        "integration": None,
    }

    batch_export_data: dict[str, t.Any] = {
        "name": "my-export",
        "destination": destination_data,
        "interval": "hour",
    }
    client.force_login(user)

    with override_settings(TEST=0, DEBUG=0):
        response = create_batch_export(
            client,
            team.pk,
            batch_export_data,
        )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert f"Invalid endpoint_url: '{endpoint_url}'" in response.json()["detail"]


@pytest.fixture
def aws_s3_integration(team, user):
    return Integration.objects.create(
        team=team,
        kind=Integration.IntegrationKind.AWS_S3,
        integration_id="prod-aws",
        config={"name": "prod-aws", "aws_account_id": "123456789012"},
        sensitive_config={"aws_access_key_id": "key", "aws_secret_access_key": "secret"},
        created_by=user,
    )


@pytest.fixture
def s3_compatible_integration(team, user):
    return Integration.objects.create(
        team=team,
        kind=Integration.IntegrationKind.S3_COMPATIBLE,
        integration_id="my-r2",
        config={"name": "my-r2", "endpoint_url": "https://account.r2.cloudflarestorage.com"},
        sensitive_config={"aws_access_key_id": "key", "aws_secret_access_key": "secret"},
        created_by=user,
    )


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
