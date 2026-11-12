import pytest

from django.test.client import Client as HttpClient

from rest_framework import status

from products.batch_exports.backend.tests.api.operations import create_batch_export, patch_batch_export
from products.batch_exports.backend.tests.api.test_create_postgres import create_postgresql_integration

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("temporal_worker", "cleanup"),
]


@pytest.mark.parametrize(
    "destination_patch, expected_status",
    [
        ({"integration": None}, status.HTTP_400_BAD_REQUEST),
        ({}, status.HTTP_200_OK),
    ],
    ids=["explicit_null_is_rejected", "omitted_keeps_integration"],
)
def test_updating_postgres_batch_export_keeps_its_integration(
    client: HttpClient, temporal, organization, team, user, destination_patch, expected_status
):
    integration = create_postgresql_integration(team, user, host="8.8.8.8")
    client.force_login(user)
    response = create_batch_export(
        client,
        team.pk,
        {
            "name": "my-postgres-destination",
            "destination": {
                "type": "Postgres",
                "config": {"database": "my-db", "schema": "public", "table_name": "my_events"},
                "integration": integration.id,
            },
            "interval": "hour",
        },
    )
    assert response.status_code == status.HTTP_201_CREATED, response.json()

    response = patch_batch_export(
        client,
        team.pk,
        response.json()["id"],
        {"destination": {"type": "Postgres", "config": {"table_name": "my_new_events"}, **destination_patch}},
    )

    assert response.status_code == expected_status, response.json()
    if expected_status == status.HTTP_200_OK:
        assert response.json()["destination"]["integration"] == integration.id
    else:
        assert response.json()["detail"].startswith("Cannot remove the integration from a Postgres batch export")
