import pytest

from django.test.client import Client as HttpClient

from rest_framework import status

from products.batch_exports.backend.tests.api.fixtures import create_integration_backed_snowflake_export
from products.batch_exports.backend.tests.api.operations import patch_batch_export

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("temporal_worker", "cleanup"),
]


@pytest.mark.parametrize("integration_value", [None, "omitted"])
def test_updating_snowflake_batch_export_rejects_removing_integration(
    client: HttpClient, temporal, organization, team, user, integration_value
):
    """An integration-backed export can't drop back to inline credentials — whether the caller sends
    `integration: null` or omits it entirely (clients re-send the full destination on update).
    """
    _, batch_export = create_integration_backed_snowflake_export(client, team, user)

    destination: dict = {"type": "Snowflake", "config": {}}
    if integration_value is None:
        destination["integration"] = None

    response = patch_batch_export(client, team.pk, batch_export["id"], {"destination": destination})
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert response.json()["detail"] == (
        "Cannot remove the integration from a Snowflake batch export that uses one. "
        "Re-send its `integration` to keep it (or a different one to swap)."
    )


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
