import pytest

from django.test.client import Client as HttpClient

from rest_framework import status

from products.batch_exports.backend.models.batch_export import BatchExportDestination
from products.batch_exports.backend.service import sync_batch_export
from products.batch_exports.backend.tests.api.fixtures import create_batch_export
from products.batch_exports.backend.tests.api.operations import (
    create_batch_export_ok,
    get_batch_export_ok,
    patch_batch_export,
)
from products.batch_exports.backend.tests.api.test_create_postgres import create_postgresql_integration

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("temporal_worker", "cleanup"),
]


def create_connection_backed_postgres_export(client: HttpClient, team, user, integration_pk: int) -> dict:
    batch_export_data = {
        "name": "my-postgres-destination",
        "interval": "hour",
        "destination": {
            "type": "Postgres",
            "config": {"database": "my-db", "schema": "public", "table_name": "my_events"},
            "integration": integration_pk,
        },
    }
    client.force_login(user)
    return create_batch_export_ok(client, team.pk, batch_export_data)


@pytest.mark.parametrize(
    "field, value", [("user", "rotated"), ("password", "rotated"), ("host", "8.8.4.4"), ("port", 5433)]
)
def test_updating_connection_backed_postgres_export_rejects_inline_connection_settings(
    client: HttpClient, temporal, organization, team, user, field, value
):
    """A connection-backed export reads its credentials and endpoint from the connection, so a
    request that sends them inline must fail instead of storing values the export never uses.
    """
    integration = create_postgresql_integration(team, user, host="8.8.8.8")
    batch_export = create_connection_backed_postgres_export(client, team, user, integration.pk)

    response = patch_batch_export(
        client,
        team.pk,
        batch_export["id"],
        {"destination": {"type": "Postgres", "config": {field: value}}},
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert f"'{field}'" in response.json()["detail"]

    batch_export = get_batch_export_ok(client, team.pk, batch_export["id"])
    assert field not in batch_export["destination"]["config"]


def test_updating_connection_backed_postgres_export_allows_other_config(
    client: HttpClient, temporal, organization, team, user
):
    integration = create_postgresql_integration(team, user, host="8.8.8.8")
    batch_export = create_connection_backed_postgres_export(client, team, user, integration.pk)

    response = patch_batch_export(
        client,
        team.pk,
        batch_export["id"],
        {"destination": {"type": "Postgres", "config": {"table_name": "other_events"}}},
    )

    assert response.status_code == status.HTTP_200_OK, response.json()
    assert response.json()["destination"]["config"]["table_name"] == "other_events"


def test_updating_inline_credential_postgres_export_still_accepts_them(
    client: HttpClient, temporal, organization, team, user
):
    """Exports created before connections existed keep their inline credentials, and the export
    reads them, so rotating a password on one of these must keep working.
    """
    destination = BatchExportDestination.objects.create(
        type=BatchExportDestination.Destination.POSTGRES,
        config={
            "user": "my-user",
            "password": "my-password",
            "host": "8.8.8.8",
            "port": 5432,
            "database": "my-db",
            "schema": "public",
            "table_name": "my_events",
        },
    )
    batch_export = create_batch_export(team, destination)
    sync_batch_export(batch_export, created=True)

    client.force_login(user)
    response = patch_batch_export(
        client,
        team.pk,
        batch_export.id,
        {"destination": {"type": "Postgres", "config": {"password": "rotated"}}},
    )

    assert response.status_code == status.HTTP_200_OK, response.json()
