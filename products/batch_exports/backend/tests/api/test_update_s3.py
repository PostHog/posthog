import pytest

from django.test.client import Client as HttpClient

from rest_framework import status

from products.batch_exports.backend.models.batch_export import S3_CREATABLE_TYPES, BatchExportDestination
from products.batch_exports.backend.tests.api.fixtures import create_batch_export as create_batch_export_orm
from products.batch_exports.backend.tests.api.operations import create_batch_export_ok, patch_batch_export

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("temporal_worker", "cleanup"),
]


def _assert_empty_inputs_rejected(client: HttpClient, team_id: int, batch_export_id, destination_type: str) -> None:
    response = patch_batch_export(
        client,
        team_id,
        batch_export_id,
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


@pytest.mark.parametrize("destination_type", sorted(S3_CREATABLE_TYPES))
def test_updating_s3_family_batch_export_validates_empty_inputs(
    client: HttpClient, temporal, organization, team, user, destination_type
):
    """Empty required string inputs are rejected when patching every creatable S3-family destination."""
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

    _assert_empty_inputs_rejected(client, team.pk, batch_export["id"], destination_type)


def test_updating_legacy_s3_batch_export_validates_empty_inputs(client: HttpClient, temporal, organization, team, user):
    """Legacy `S3` rows can no longer be created, but existing ones must remain patchable and validated."""
    destination = BatchExportDestination.objects.create(
        type="S3",
        config={
            "bucket_name": "my-s3-bucket",
            "region": "us-east-1",
            "prefix": "events/",
            "aws_access_key_id": "abc123",
            "aws_secret_access_key": "secret",
        },
    )
    batch_export = create_batch_export_orm(team, destination)

    client.force_login(user)
    _assert_empty_inputs_rejected(client, team.pk, str(batch_export.id), "S3")
