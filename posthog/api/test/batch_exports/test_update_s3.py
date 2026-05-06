import pytest

from django.test.client import Client as HttpClient

from rest_framework import status

from posthog.api.test.batch_exports.operations import create_batch_export_ok, patch_batch_export
from posthog.batch_exports.models import S3_FAMILY_TYPES

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("temporal_worker", "cleanup"),
]


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
