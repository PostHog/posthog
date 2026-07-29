import pytest

from django.test.client import Client as HttpClient

from rest_framework import status

from posthog.models.integration import Integration

from products.batch_exports.backend.tests.api.operations import create_batch_export

pytestmark = [
    pytest.mark.django_db,
]


@pytest.fixture(autouse=True)
def mock_batch_export_schedule(monkeypatch) -> None:
    monkeypatch.setattr("products.batch_exports.backend.api.batch_export.sync_batch_export", lambda *_, **__: None)


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
    client: HttpClient, mode, copy_inputs, expected_status, organization, team, user
):
    integration = Integration.objects.create(
        team=team,
        kind=Integration.IntegrationKind.REDSHIFT,
        integration_id="prod-redshift",
        config={
            "name": "prod-redshift",
            "authentication_type": "password",
            "user": "user",
        },
        sensitive_config={"password": "my-password"},
        created_by=user,
    )

    destination_data = {
        "type": "Redshift",
        "config": {
            "database": "my-db",
            "host": "8.8.8.8",
            "port": 5439,
            "schema": "public",
            "table_name": "my_events",
            "mode": mode,
            "copy_inputs": copy_inputs,
        },
        "integration": integration.id,
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
