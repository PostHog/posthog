import pytest
from unittest import mock

from django.test.client import Client as HttpClient

from rest_framework import status

from products.batch_exports.backend.tests.api.conftest import assert_is_daily_schedule, describe_schedule
from products.batch_exports.backend.tests.api.operations import create_batch_export

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("temporal_worker", "cleanup"),
]


@pytest.fixture
def enable_backfilling_workflows(team):
    with mock.patch(
        "products.batch_exports.backend.api.batch_export.posthoganalytics.feature_enabled", return_value=True
    ) as feature_enabled:
        yield

        feature_enabled.assert_any_call(
            "backfill-workflows-destination",
            str(team.uuid),
            groups={"organization": str(team.organization.id)},
            group_properties={
                "organization": {
                    "id": str(team.organization.id),
                    "created_at": team.organization.created_at,
                }
            },
            send_feature_flag_events=False,
        )


def test_creating_workflows_batch_export(
    client: HttpClient, temporal, organization, team, user, enable_backfilling_workflows
):
    """Test that we can create a Workflows batch export if the feature flag is enabled."""

    destination_data = {
        "type": "Workflows",
        "config": {
            "hog_function_id": "aaaa-bbbb-cccc",
        },
        "integration": None,
    }

    batch_export_data = {
        "name": "my-workflows-destination",
        "destination": destination_data,
        "interval": "day",
    }

    client.force_login(user)
    response = create_batch_export(
        client,
        team.pk,
        batch_export_data,
    )

    assert response.status_code == status.HTTP_201_CREATED, response.json()

    data = response.json()
    assert data["destination"] == destination_data

    schedule = describe_schedule(temporal, data["id"])
    assert_is_daily_schedule(schedule, 0)


def test_creating_workflows_batch_export_fails_if_feature_flag_is_not_enabled(
    client: HttpClient, temporal, organization, team, user
):
    """Test that creating a Workflows batch export fails if the feature flag is not enabled."""

    destination_data = {
        "type": "Workflows",
        "config": {
            "hog_function_id": "aaaa-bbbb-cccc",
        },
        "integration": None,
    }

    batch_export_data = {
        "name": "my-workflows-destination",
        "destination": destination_data,
        "interval": "day",
    }

    client.force_login(user)

    response = create_batch_export(
        client,
        team.pk,
        batch_export_data,
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
    assert "Backfilling Workflows is not enabled for this team." in response.json()["detail"]
