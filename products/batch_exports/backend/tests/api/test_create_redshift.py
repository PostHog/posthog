import pytest

from django.test.client import Client as HttpClient

from rest_framework import status

from products.batch_exports.backend.tests.api.operations import create_batch_export

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("temporal_worker", "cleanup"),
]


@pytest.mark.parametrize(
    "mode,copy_inputs,expected_status",
    [
        (
            "INSERT",
            {},
            status.HTTP_201_CREATED,
        ),
        (
            "INSERT",
            None,
            status.HTTP_201_CREATED,
        ),
        (
            "COPY",
            {
                "s3_bucket": "my-production-s3-bucket",
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": {"aws_access_key_id": "abc123", "aws_secret_access_key": "secret"},
                "authorization": "default",
            },
            status.HTTP_201_CREATED,
        ),
        (
            "COPY",
            {
                "s3_bucket": "my-production-s3-bucket",
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": {"aws_access_key_id": "abc123", "aws_secret_access_key": "secret"},
                "authorization": {"aws_access_key_id": "abc123", "aws_secret_access_key": "secret"},
            },
            status.HTTP_201_CREATED,
        ),
        # Missing required 's3_bucket'
        (
            "COPY",
            {
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": {"aws_access_key_id": "abc123", "aws_secret_access_key": "secret"},
                "authorization": "default",
            },
            status.HTTP_400_BAD_REQUEST,
        ),
        # Missing required 'region_name'
        (
            "COPY",
            {
                "s3_bucket": "my-production-s3-bucket",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": {"aws_access_key_id": "abc123", "aws_secret_access_key": "secret"},
                "authorization": "default",
            },
            status.HTTP_400_BAD_REQUEST,
        ),
        # Missing required 'aws_secret_access_key' in 'bucket_credentials
        (
            "COPY",
            {
                "s3_bucket": "my-production-s3-bucket",
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": {"aws_access_key_id": "abc123"},
                "authorization": "default",
            },
            status.HTTP_400_BAD_REQUEST,
        ),
        # Empty 'bucket_credentials'
        (
            "COPY",
            {
                "s3_bucket": "my-production-s3-bucket",
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": {},
                "authorization": "default",
            },
            status.HTTP_400_BAD_REQUEST,
        ),
        # Empty 'authorization'
        (
            "COPY",
            {
                "s3_bucket": "my-production-s3-bucket",
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": {"aws_access_key_id": "abc123", "aws_secret_access_key": "secret"},
                "authorization": {},
            },
            status.HTTP_400_BAD_REQUEST,
        ),
        # Empty 'authorization' as IAMRole
        (
            "COPY",
            {
                "s3_bucket": "my-production-s3-bucket",
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": {"aws_access_key_id": "abc123", "aws_secret_access_key": "secret"},
                "authorization": "",
            },
            status.HTTP_400_BAD_REQUEST,
        ),
    ],
)
def test_create_redshift_batch_export_validates_copy_inputs(
    client: HttpClient, mode, copy_inputs, expected_status, temporal, organization, team, user
):
    """Test creating a BatchExport with Redshift destination validates inputs for 'COPY'."""

    destination_data = {
        "type": "Redshift",
        "config": {
            "user": "user",
            "password": "my-password",
            "database": "my-db",
            "host": "localhost",
            "schema": "public",
            "table_name": "my_events",
            "mode": mode,
            "copy_inputs": copy_inputs,
        },
    }

    batch_export_data = {
        "name": "my-production-redshiftn-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)

    response = create_batch_export(
        client,
        team.pk,
        batch_export_data,
    )

    assert response.status_code == expected_status, response.json()

    if expected_status == status.HTTP_400_BAD_REQUEST:
        assert "Missing required" in response.json()["detail"]
