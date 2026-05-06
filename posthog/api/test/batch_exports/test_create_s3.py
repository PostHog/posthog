import typing as t

import pytest

from django.test import override_settings
from django.test.client import Client as HttpClient

from rest_framework import status

from posthog.api.test.batch_exports.operations import create_batch_export
from posthog.batch_exports.models import S3_FAMILY_TYPES

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

# TODO: 'S3' can be removed as a destination type once the legacy alias is no longer supported


@pytest.mark.parametrize(
    "destination_type,extra_config,expected_persisted_type",
    [
        # Legacy `S3` alias: no endpoint_url → normalized to AwsS3 on save
        ("S3", {}, "AwsS3"),
        # Legacy `S3` alias: endpoint_url set → normalized to S3Compatible on save
        ("S3", {"endpoint_url": "https://localhost:9000"}, "S3Compatible"),
        # Direct AwsS3 (with AWS-only encryption field)
        ("AwsS3", {"encryption": "AES256"}, "AwsS3"),
        # Direct S3Compatible (endpoint_url is required)
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
    """Posting any S3-family destination type creates a batch export and persists with the expected type."""
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


@pytest.mark.parametrize("destination_type", sorted(S3_FAMILY_TYPES))
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
        *((dt, field) for dt in sorted(S3_FAMILY_TYPES) for field in ("aws_access_key_id", "aws_secret_access_key")),
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
        "type": "S3",
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
    # Only types that accept `endpoint_url` reach the SSRF check.
    ["S3", "S3Compatible"],
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
