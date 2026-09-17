import pytest

from django.test.client import Client as HttpClient

from rest_framework import status

from products.batch_exports.backend.tests.api.fixtures import create_integration_backed_snowflake_export
from products.batch_exports.backend.tests.api.operations import patch_batch_export

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("temporal_worker", "cleanup"),
]


def test_updating_snowflake_batch_export_rejects_removing_integration(
    client: HttpClient, temporal, organization, team, user
):
    """Sending `integration: null` is a removal, and a Snowflake export cannot authenticate without one."""
    _, batch_export = create_integration_backed_snowflake_export(client, team, user)

    response = patch_batch_export(
        client,
        team.pk,
        batch_export["id"],
        {"destination": {"type": "Snowflake", "config": {}, "integration": None}},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert response.json()["detail"] == "Integration is required for Snowflake batch exports"


def test_updating_snowflake_batch_export_keeps_its_integration_when_omitted(
    client: HttpClient, temporal, organization, team, user
):
    """Omitting `integration` on a PATCH keeps the linked one, so a config-only edit succeeds."""
    integration, batch_export = create_integration_backed_snowflake_export(client, team, user)

    response = patch_batch_export(
        client,
        team.pk,
        batch_export["id"],
        {"destination": {"type": "Snowflake", "config": {"schema": "new_schema"}}},
    )
    assert response.status_code == status.HTTP_200_OK, response.json()
    assert response.json()["destination"]["integration"] == integration.id


def test_updating_snowflake_batch_export_rejects_inline_credentials(
    client: HttpClient, temporal, organization, team, user
):
    """A migrated export still stores its old credentials, so a client that echoes them back is rejected."""
    integration, batch_export = create_integration_backed_snowflake_export(client, team, user)

    response = patch_batch_export(
        client,
        team.pk,
        batch_export["id"],
        {
            "destination": {
                "type": "Snowflake",
                "config": {"schema": "new_schema", "account": "my-account", "password": "hunter2"},
                "integration": integration.id,
            }
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert response.json()["detail"] == "Configuration has unknown field/s: 'account', 'password'"


def test_updating_integration_backed_snowflake_export_allows_config_patch_with_integration(
    client: HttpClient, temporal, organization, team, user
):
    """Updating config while re-sending the integration succeeds and keeps it linked."""
    integration, batch_export = create_integration_backed_snowflake_export(client, team, user)

    response = patch_batch_export(
        client,
        team.pk,
        batch_export["id"],
        {"destination": {"type": "Snowflake", "config": {"schema": "new_schema"}, "integration": integration.id}},
    )
    assert response.status_code == status.HTTP_200_OK, response.json()
    assert response.json()["destination"]["config"]["schema"] == "new_schema"
    assert response.json()["destination"]["integration"] == integration.id
