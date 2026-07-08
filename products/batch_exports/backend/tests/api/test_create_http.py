import pytest

from django.test.client import Client as HttpClient

from rest_framework import status

from products.batch_exports.backend.tests.api.operations import create_batch_export

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("temporal_worker", "cleanup"),
]


@pytest.mark.parametrize(
    "model,expected_status,expected_error",
    [
        ("events", status.HTTP_201_CREATED, None),
        (None, status.HTTP_201_CREATED, None),
        ("persons", status.HTTP_400_BAD_REQUEST, "HTTP batch exports only support the events model"),
    ],
)
def test_creating_http_batch_export_only_allows_events_model(
    client: HttpClient, temporal, organization, team, user, model, expected_status, expected_error
):
    """HTTP batch exports are used for migrations, and therefore only support the events model."""

    destination_data = {
        "type": "HTTP",
        "config": {
            "url": "https://us.i.posthog.com/batch/",
            "token": "secret-token",
        },
    }

    batch_export_data = {
        "name": "my-http-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    if model is not None:
        batch_export_data["model"] = model

    client.force_login(user)
    response = create_batch_export(
        client,
        team.pk,
        batch_export_data,
    )

    assert response.status_code == expected_status, response.json()

    if expected_error:
        assert response.json()["detail"] == expected_error
