import pytest

from django.test import override_settings
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


def create_redshift_integration(team, user) -> Integration:
    return Integration.objects.create(
        team=team,
        kind=Integration.IntegrationKind.REDSHIFT,
        integration_id="prod-redshift",
        config={
            "name": "prod-redshift",
            "authentication_type": "password",
            "user": "batch_exporter",
        },
        sensitive_config={"password": "secret"},
        created_by=user,
    )


def test_creating_redshift_batch_export_using_integration(client: HttpClient, organization, team, user) -> None:
    integration = create_redshift_integration(team, user)

    client.force_login(user)
    response = create_batch_export(
        client,
        team.pk,
        {
            "name": "my-redshift-destination",
            "destination": {
                "type": "Redshift",
                "config": {
                    "database": "analytics",
                    "host": "8.8.8.8",
                    "port": 5439,
                    "schema": "public",
                    "table_name": "events",
                    "mode": "INSERT",
                },
                "integration": integration.id,
            },
            "interval": "hour",
        },
    )

    assert response.status_code == status.HTTP_201_CREATED, response.json()
    assert response.json()["destination"]["integration"] == integration.id
    assert "password" not in response.json()["destination"]["config"]
    assert response.json()["destination"]["config"]["host"] == "8.8.8.8"


def test_creating_redshift_batch_export_without_integration_is_rejected(
    client: HttpClient, organization, team, user
) -> None:
    client.force_login(user)
    response = create_batch_export(
        client,
        team.pk,
        {
            "name": "my-redshift-destination",
            "destination": {
                "type": "Redshift",
                "config": {
                    "user": "user",
                    "password": "my-password",
                    "database": "analytics",
                    "host": "8.8.8.8",
                    "port": 5439,
                    "schema": "public",
                    "table_name": "events",
                    "mode": "INSERT",
                },
            },
            "interval": "hour",
        },
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert "Integration is required for Redshift batch exports" in response.json()["detail"]


def test_creating_redshift_batch_export_rejects_mismatched_integration_kind(
    client: HttpClient, organization, team, user
) -> None:
    integration = Integration.objects.create(
        team=team,
        kind=Integration.IntegrationKind.AWS_S3,
        integration_id="prod-aws",
        config={"name": "prod-aws", "aws_account_id": "123456789012"},
        sensitive_config={"aws_access_key_id": "key", "aws_secret_access_key": "secret"},
        created_by=user,
    )

    client.force_login(user)
    response = create_batch_export(
        client,
        team.pk,
        {
            "name": "my-redshift-destination",
            "destination": {
                "type": "Redshift",
                "config": {
                    "database": "analytics",
                    "schema": "public",
                    "table_name": "events",
                    "mode": "INSERT",
                },
                "integration": integration.id,
            },
            "interval": "hour",
        },
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert response.json()["detail"] == "Integration is not a Redshift integration."


@pytest.mark.parametrize("host", ["169.254.169.254", "127.0.0.1", "10.0.0.1", "192.168.1.1"])
def test_creating_redshift_batch_export_validates_destination_host(
    client: HttpClient, organization, team, user, host
) -> None:
    integration = create_redshift_integration(team, user)

    client.force_login(user)
    with override_settings(TEST=0, DEBUG=0):
        response = create_batch_export(
            client,
            team.pk,
            {
                "name": "my-redshift-destination",
                "destination": {
                    "type": "Redshift",
                    "config": {
                        "database": "analytics",
                        "host": host,
                        "port": 5439,
                        "schema": "public",
                        "table_name": "events",
                        "mode": "INSERT",
                    },
                    "integration": integration.id,
                },
                "interval": "hour",
            },
        )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert f"Invalid host: '{host}'" in response.json()["detail"]
