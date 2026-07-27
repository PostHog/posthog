import pytest

from django.test.client import Client as HttpClient

from rest_framework import status

from products.batch_exports.backend.tests.api.operations import (
    create_batch_export_ok,
    get_batch_export_ok,
    patch_batch_export,
)

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("temporal_worker", "cleanup"),
]


def test_can_patch_redshift_batch_export(client: HttpClient, temporal, organization, team, user):
    """Test we can patch a Redshift batch export preserving credentials."""
    destination_data = {
        "type": "Redshift",
        "config": {
            "user": "user",
            "password": "my-password",
            "database": "my-db",
            "host": "localhost",
            "schema": "public",
            "table_name": "my_events",
            "mode": "COPY",
            "copy_inputs": {
                "s3_bucket": "my-production-s3-bucket",
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": {"aws_access_key_id": "abc123", "aws_secret_access_key": "secret"},
                "authorization": {"aws_access_key_id": "abc123", "aws_secret_access_key": "secret"},
            },
        },
    }

    batch_export_data = {
        "name": "my-production-redshiftn-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)

    batch_export = create_batch_export_ok(
        client,
        team.pk,
        batch_export_data,
    )

    # Updates bucket name, leaves everything else untouched.
    new_destination_data = {
        "type": "Redshift",
        "config": {
            "copy_inputs": {
                "s3_bucket": "my-new-production-s3-bucket",
            },
        },
    }

    new_batch_export_data = {
        "destination": new_destination_data,
    }

    response = patch_batch_export(client, team.pk, batch_export["id"], new_batch_export_data)
    assert response.status_code == status.HTTP_200_OK, response.json()

    # Verify the bucket name update worked
    batch_export = get_batch_export_ok(client, team.pk, batch_export["id"])
    assert batch_export["destination"]["type"] == "Redshift"
    assert batch_export["destination"]["config"]["copy_inputs"]["s3_bucket"] == "my-new-production-s3-bucket"
