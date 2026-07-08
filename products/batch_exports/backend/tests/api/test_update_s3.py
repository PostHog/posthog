import pytest

from django.test.client import Client as HttpClient

from rest_framework import status

from posthog.models.integration import Integration

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


_S3_FAMILY_INTEGRATIONS = [
    ("AwsS3", Integration.IntegrationKind.AWS_S3, {"name": "prod-aws", "aws_account_id": "123456789012"}),
    (
        "S3Compatible",
        Integration.IntegrationKind.S3_COMPATIBLE,
        {"name": "my-r2", "endpoint_url": "https://account.r2.cloudflarestorage.com"},
    ),
]


def _create_integration_backed_export(client: HttpClient, team, user, destination_type, kind, integration_config):
    integration = Integration.objects.create(
        team=team,
        kind=kind,
        integration_id=integration_config["name"],
        config=integration_config,
        sensitive_config={"aws_access_key_id": "key", "aws_secret_access_key": "secret"},
        created_by=user,
    )
    client.force_login(user)
    batch_export = create_batch_export_ok(
        client,
        team.pk,
        {
            "name": "my-export",
            "interval": "hour",
            "destination": {
                "type": destination_type,
                # No inline credentials (nor endpoint_url) — they come from the integration.
                "config": {"bucket_name": "my-bucket", "region": "us-east-1", "prefix": "events/"},
                "integration": integration.id,
            },
        },
    )
    return integration, batch_export


@pytest.mark.parametrize("destination_type,kind,integration_config", _S3_FAMILY_INTEGRATIONS)
@pytest.mark.parametrize("integration_value", [None, "omitted"])
def test_updating_s3_family_batch_export_rejects_removing_integration(
    client: HttpClient,
    temporal,
    organization,
    team,
    user,
    destination_type,
    kind,
    integration_config,
    integration_value,
):
    """An integration-backed export can't drop back to inline credentials — whether the caller
    sends `integration: null` or omits it entirely (clients re-send the full destination on update).
    """
    _, batch_export = _create_integration_backed_export(client, team, user, destination_type, kind, integration_config)

    destination: dict = {"type": destination_type, "config": {}}
    if integration_value is None:
        destination["integration"] = None

    response = patch_batch_export(client, team.pk, batch_export["id"], {"destination": destination})
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert response.json()["detail"] == (
        "Cannot remove the integration from an S3 batch export that uses one. "
        "Re-send its `integration` to keep it (or a different one to swap)."
    )


@pytest.mark.parametrize("destination_type,kind,integration_config", _S3_FAMILY_INTEGRATIONS)
def test_updating_integration_backed_s3_export_allows_config_patch_with_integration(
    client: HttpClient, temporal, organization, team, user, destination_type, kind, integration_config
):
    """Updating config while re-sending the integration succeeds and keeps it linked."""
    integration, batch_export = _create_integration_backed_export(
        client, team, user, destination_type, kind, integration_config
    )

    response = patch_batch_export(
        client,
        team.pk,
        batch_export["id"],
        {"destination": {"type": destination_type, "config": {"prefix": "new-prefix/"}, "integration": integration.id}},
    )
    assert response.status_code == status.HTTP_200_OK, response.json()
    assert response.json()["destination"]["config"]["prefix"] == "new-prefix/"
    assert response.json()["destination"]["integration"] == integration.id


def test_updating_legacy_s3_batch_export_rejects_integration(client: HttpClient, temporal, organization, team, user):
    """The legacy `S3` type doesn't support integration-based credentials, so linking one is rejected."""
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
    integration = Integration.objects.create(
        team=team,
        kind=Integration.IntegrationKind.AWS_S3,
        integration_id="prod-aws",
        config={"name": "prod-aws", "aws_account_id": "123456789012"},
        sensitive_config={"aws_access_key_id": "key", "aws_secret_access_key": "secret"},
        created_by=user,
    )

    client.force_login(user)
    response = patch_batch_export(
        client,
        team.pk,
        str(batch_export.id),
        {"destination": {"type": "S3", "config": {}, "integration": integration.id}},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert response.json()["detail"] == "S3 destinations do not support integration-based credentials."
