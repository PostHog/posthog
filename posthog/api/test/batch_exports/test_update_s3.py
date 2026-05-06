import pytest

from django.test.client import Client as HttpClient

from rest_framework import status

from posthog.api.test.batch_exports.operations import create_batch_export_ok, get_batch_export_ok, patch_batch_export
from posthog.batch_exports.models import S3_FAMILY_TYPES

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("temporal_worker", "cleanup"),
]


def test_patch_with_legacy_s3_type_preserves_normalized_type(
    client: HttpClient,
    temporal,
    organization,
    team,
    user,
):
    """Assert PATCH with the legacy `type="S3"` alias is silently coerced to the row's already-normalized type.

    Realistic scenario: a stale frontend or third-party caller continues to send `type="S3"`
    after this PR ships. New rows get normalized to `AwsS3` / `S3Compatible` on create, so a
    naive type-change check would 400 every PATCH from such callers. The validator coerces
    the legacy alias to the existing type so they keep working.
    """
    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": "my-production-s3-bucket",
            "region": "us-east-1",
            "prefix": "posthog-events/",
            "aws_access_key_id": "abc123",
            "aws_secret_access_key": "secret",
        },
    }

    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)
    batch_export = create_batch_export_ok(client, team.pk, batch_export_data)

    # Create normalized to AwsS3 (no endpoint_url).
    assert batch_export["destination"]["type"] == "AwsS3"

    # Stale caller PATCHes with the legacy alias plus a config change.
    response = patch_batch_export(
        client,
        team.pk,
        batch_export["id"],
        {
            "destination": {
                "type": "S3",
                "config": {"bucket_name": "my-new-bucket"},
            },
        },
    )
    assert response.status_code == status.HTTP_200_OK, response.json()

    # The row's type stays AwsS3, but the config update applied.
    refreshed = get_batch_export_ok(client, team.pk, batch_export["id"])
    assert refreshed["destination"]["type"] == "AwsS3"
    assert refreshed["destination"]["config"]["bucket_name"] == "my-new-bucket"


@pytest.mark.parametrize("destination_type", sorted(S3_FAMILY_TYPES))
def test_updating_s3_family_batch_export_validates_empty_inputs(
    client: HttpClient, temporal, organization, team, user, destination_type
):
    """Empty required string inputs are rejected when patching every S3-family destination."""
    initial_config = {
        "bucket_name": "my-s3-bucket",
        "region": "us-east-1",
        "prefix": "events/",
        "aws_access_key_id": "abc123",
        "aws_secret_access_key": "secret",
        "file_format": "JSONLines",
        "compression": "gzip",
    }
    if destination_type == "S3Compatible":
        # S3Compatible additionally requires `endpoint_url` to be present.
        initial_config["endpoint_url"] = "https://localhost:9000"

    client.force_login(user)
    batch_export = create_batch_export_ok(
        client,
        team.pk,
        {
            "name": "my-s3-bucket",
            "destination": {"type": destination_type, "config": initial_config},
            "interval": "hour",
        },
    )

    response = patch_batch_export(
        client,
        team.pk,
        batch_export["id"],
        {
            "destination": {
                "type": destination_type,
                "config": {
                    "bucket_name": "my-new-bucket",
                    "aws_access_key_id": "",
                    "aws_secret_access_key": "",
                },
            },
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["detail"] == "The following inputs are empty: ['aws_access_key_id', 'aws_secret_access_key']"
