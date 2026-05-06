import typing as t

import pytest

from django.test import override_settings
from django.test.client import Client as HttpClient

from rest_framework import status

from posthog.api.test.batch_exports.operations import create_batch_export

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("temporal_worker", "cleanup"),
]


@pytest.mark.parametrize(
    "file_format,compression,expected_error_message",
    [
        (
            "JSONLines",
            None,
            None,
        ),
        (
            "JSONLines",
            "gzip",
            None,
        ),
        (
            "JSONLines",
            "zstd",
            "Compression zstd is not supported for file format JSONLines. Supported compressions are ['gzip', 'brotli']",
        ),
        (
            "Parquet",
            None,
            None,
        ),
        (
            "Parquet",
            "gzip",
            None,
        ),
        (
            "Parquet",
            "brotli",
            None,
        ),
        (
            "Parquet",
            "zstd",
            None,
        ),
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


def test_create_s3_batch_export_validates_empty_inputs(client: HttpClient, temporal, organization, team, user):
    """Test creating a BatchExport with S3 destination validates that expected inputs are not empty."""

    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": "my-s3-bucket",
            "region": "us-east-1",
            "prefix": "events/",
            "aws_access_key_id": "",
            "aws_secret_access_key": "",
            "file_format": "JSONLines",
            "compression": "gzip",
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

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["detail"] == "The following inputs are empty: ['aws_access_key_id', 'aws_secret_access_key']"


def test_create_s3_batch_export_validates_missing_inputs(client: HttpClient, temporal, organization, team, user):
    """Test creating a BatchExport with S3 destination validates that expected inputs are not missing."""

    config = {
        "bucket_name": "my-s3-bucket",
        "region": "us-east-1",
        "prefix": "events/",
        "aws_access_key_id": "something",
        "aws_secret_access_key": "something",
        "file_format": "JSONLines",
        "compression": "gzip",
    }

    client.force_login(user)

    for key in ("aws_access_key_id", "aws_secret_access_key"):
        # Check that we validate each key missing invidually first
        destination_data = {"type": "S3", "config": {k: v for k, v in config.items() if k != key}}

        data = {
            "name": "my-s3-bucket",
            "destination": destination_data,
            "interval": "hour",
        }

        response = create_batch_export(
            client,
            team.pk,
            data,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, key
        assert response.json()["detail"] == f"Configuration missing required field: '{key}'"

    response_missing_both = create_batch_export(
        client,
        team.pk,
        {
            "name": "my-s3-bucket",
            "destination": {k: v for k, v in destination_data.items() if k != "aws_secret_access_key"},
            "interval": "hour",
        },
    )

    assert response_missing_both.status_code == status.HTTP_400_BAD_REQUEST


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
def test_creating_S3_batch_export_fails_if_using_invalid_endpoint_url(
    client: HttpClient, temporal, organization, team, user, endpoint_url
):
    """Test that creating an S3 batch export fails if passing an internal IP as endpoint URL.

    Last time I checked, we are not S3.
    """

    interval = "hour"

    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": "my-production-s3-bucket",
            "region": "us-east-1",
            "prefix": "posthog-events/",
            "aws_access_key_id": "abc123",
            "aws_secret_access_key": "secret",
            "use_virtual_style_addressing": True,
            "endpoint_url": endpoint_url,
        },
        "integration": None,
    }

    batch_export_data: dict[str, t.Any] = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": interval,
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
