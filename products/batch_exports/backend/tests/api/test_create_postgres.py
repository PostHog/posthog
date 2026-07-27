import pytest

from django.test import override_settings
from django.test.client import Client as HttpClient

from rest_framework import status

from posthog.models.integration import Integration

from products.batch_exports.backend.tests.api.operations import create_batch_export

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("temporal_worker", "cleanup"),
]


def create_postgresql_integration(team, user, host: str) -> Integration:
    """Create a PostgreSQL integration storing connection details, including the host.

    For integration-backed Postgres batch exports the connection credentials (including
    the host) live in the Integration rather than in the destination's `config`.
    """
    return Integration.objects.create(
        team=team,
        kind=Integration.IntegrationKind.POSTGRESQL,
        integration_id=f"{team.pk}-{host}-5432-user",
        config={
            "host": host,
            "port": 5432,
            "user": "user",
            "ssl_mode": "require",
            "ssl_root_cert": None,
        },
        sensitive_config={"password": "my-password"},
        created_by=user,
    )


def test_creating_postgres_batch_export_using_integration(client: HttpClient, temporal, organization, team, user):
    """Test that we can create a Postgres batch export backed by an integration.

    The host lives in the linked Integration rather than in `config`, so the destination
    config only carries non-credential fields. This path used to raise a `KeyError` (HTTP
    500) while SSRF-validating `config["host"]`, which does not exist for integration-backed
    exports.
    """
    integration = create_postgresql_integration(team, user, host="8.8.8.8")

    destination_data = {
        "type": "Postgres",
        "config": {
            "database": "my-db",
            "schema": "public",
            "table_name": "my_events",
        },
        "integration": integration.id,
    }

    batch_export_data = {
        "name": "my-postgres-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)
    response = create_batch_export(client, team.pk, batch_export_data)

    assert response.status_code == status.HTTP_201_CREATED, response.json()
    assert response.json()["destination"]["integration"] == integration.id


@pytest.mark.parametrize(
    "host",
    [
        "169.254.169.254",
        "127.0.0.1",
        "10.0.0.1",
        "192.168.1.1",
    ],
)
def test_creating_postgres_batch_export_validates_integration_host(
    client: HttpClient, temporal, organization, team, user, host
):
    """Test that the integration's host is SSRF-validated when creating a Postgres batch export.

    The host comes from the linked Integration, not from `config`, so this path must still
    reject internal/private hosts rather than skipping host validation altogether.
    """
    integration = create_postgresql_integration(team, user, host=host)

    destination_data = {
        "type": "Postgres",
        "config": {
            "database": "my-db",
            "schema": "public",
            "table_name": "my_events",
        },
        "integration": integration.id,
    }

    batch_export_data = {
        "name": "my-postgres-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)
    with override_settings(TEST=0, DEBUG=0):
        response = create_batch_export(client, team.pk, batch_export_data)

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert f"Invalid host: '{host}'" in response.json()["detail"]


def test_creating_postgres_batch_export_without_integration_is_rejected(
    client: HttpClient, temporal, organization, team, user
):
    """Test that creating a new Postgres batch export without an integration is rejected.

    New Postgres exports must store credentials in a linked Integration; inline credentials (the
    legacy path) are no longer accepted on create.
    """
    destination_data = {
        "type": "Postgres",
        "config": {
            "user": "user",
            "password": "my-password",
            "host": "8.8.8.8",
            "port": 5432,
            "database": "my-db",
            "schema": "public",
            "table_name": "my_events",
        },
    }

    batch_export_data = {
        "name": "my-postgres-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)
    response = create_batch_export(client, team.pk, batch_export_data)

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert "Integration is required for Postgres batch exports" in response.json()["detail"]
