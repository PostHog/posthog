import pytest

from django.test.client import Client as HttpClient

from rest_framework import status

from posthog.models.integration import Integration

from products.batch_exports.backend.models.batch_export import BatchExportDestination
from products.batch_exports.backend.tests.api.fixtures import create_batch_export as create_batch_export_orm
from products.batch_exports.backend.tests.api.operations import create_batch_export_ok, patch_batch_export

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("temporal_worker", "cleanup"),
]


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
def test_updating_s3_family_batch_export_requires_an_integration(
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
    """An export can't drop its integration: sending `integration: null` is rejected, and omitting
    it entirely keeps the one already linked.
    """
    integration, batch_export = _create_integration_backed_export(
        client, team, user, destination_type, kind, integration_config
    )

    destination: dict = {"type": destination_type, "config": {"prefix": "new-prefix/"}}
    if integration_value is None:
        destination["integration"] = None

    response = patch_batch_export(client, team.pk, batch_export["id"], {"destination": destination})

    if integration_value is None:
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["detail"] == f"Integration is required for {destination_type} batch exports"
    else:
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["destination"]["integration"] == integration.id


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


@pytest.mark.parametrize("destination_type,kind,integration_config", _S3_FAMILY_INTEGRATIONS)
def test_updating_migrated_s3_batch_export_ignores_credentials_left_in_stored_config(
    client: HttpClient, temporal, organization, team, user, destination_type, kind, integration_config
):
    """Exports migrated onto an integration still hold their old credentials in stored config.

    Those stale values must not make the export unpatchable: only the submitted config is checked
    for credential fields.
    """
    integration, batch_export = _create_integration_backed_export(
        client, team, user, destination_type, kind, integration_config
    )
    destination = BatchExportDestination.objects.get(batchexport__id=batch_export["id"])
    destination.config = {**destination.config, "aws_access_key_id": "stale", "aws_secret_access_key": "stale"}
    destination.save()

    response = patch_batch_export(
        client,
        team.pk,
        batch_export["id"],
        {"destination": {"type": destination_type, "config": {"prefix": "new-prefix/"}, "integration": integration.id}},
    )
    assert response.status_code == status.HTTP_200_OK, response.json()
    assert response.json()["destination"]["config"]["prefix"] == "new-prefix/"


def test_updating_legacy_s3_batch_export_is_rejected(client: HttpClient, temporal, organization, team, user):
    """The legacy `S3` type has been migrated away and accepts no writes."""
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
    response = patch_batch_export(
        client,
        team.pk,
        str(batch_export.id),
        {"destination": {"type": "S3", "config": {"prefix": "new-prefix/"}}},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert "deprecated" in response.json()["detail"]
