import pytest
from django.test.client import Client as HttpClient
from rest_framework import status

from posthog.api.test.batch_exports.conftest import start_test_worker
from posthog.api.test.batch_exports.operations import create_batch_export
from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.temporal.client import sync_connect

pytestmark = [
    pytest.mark.django_db,
]


def test_create_batch_export_with_interval_schedule(client: HttpClient):
    """Test creating a BatchExport.

    When creating a BatchExport, we should create a corresponding Schedule in
    Temporal as described by the associated BatchExportSchedule model. In this
    test we assert this Schedule is created in
    Temporal.
    """
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

    data = response.json()

    # We should not get the aws_access_key_id or aws_secret_access_key back, so
    # remove that from the data we expect.
    batch_export_data["destination"]["config"].pop("aws_access_key_id")
    batch_export_data["destination"]["config"].pop("aws_secret_access_key")
    assert data["destination"] == batch_export_data["destination"]

    # We should match on top level fields.
    assert {"name": data["name"], "interval": data["interval"]} == {
        "name": "my-production-s3-bucket-destination",
        "interval": "hour",
    }


def test_cannot_create_a_batch_export_for_another_organization(client: HttpClient):
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
    create_team(organization)
    user = create_user("test@user.com", "Test User", organization)

    another_organization = create_organization("Another Test Org")
    another_team = create_team(another_organization)

    with start_test_worker(temporal):
        client.force_login(user)
        response = create_batch_export(
            client,
            another_team.pk,
            batch_export_data,
        )

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
