import pytest
from django.test.client import Client as HttpClient
from rest_framework import status

from posthog.api.test.batch_exports.operations import create_batch_export
from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.api.test.batch_exports.conftest import start_test_worker
from posthog.temporal.common.client import sync_connect

pytestmark = [
    pytest.mark.django_db,
]


@pytest.mark.parametrize("date_from", ["30d", "7d", "24h"])
def test_batch_export_empty_app_metrics(client: HttpClient, date_from):
    """Test empty batch export app metrics."""
    temporal = sync_connect()

    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": "my-production-s3-bucket",
            "region": "us-east-1",
            "prefix": "posthog-events/",
            "aws_access_key_id": "abc123",
            "aws_secret_access_key": "secret",
        },
    }

    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    organization = create_organization("Test Org")
    team = create_team(organization)
    user = create_user("test@user.com", "Test User", organization)
    client.force_login(user)

    with start_test_worker(temporal):
        response = create_batch_export(
            client,
            team.pk,
            batch_export_data,
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()

        batch_export_id = response.json()["id"]

    response = client.get(f"/api/projects/{team.pk}/app_metrics/{batch_export_id}", {"date_from": date_from})
    metrics = response.json()

    assert metrics["metrics"][0]["successes"] == []
    assert metrics["metrics"][0]["failures"] == []
    assert metrics["metrics"][0]["totals"]["successes"] == 0
    assert metrics["metrics"][0]["totals"]["failures"] == 0
