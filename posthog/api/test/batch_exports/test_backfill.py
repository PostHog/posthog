from django.test.client import Client as HttpClient
import pytest

from rest_framework import status
from posthog.api.test.batch_exports.conftest import start_test_worker
from posthog.api.test.batch_exports.operations import backfill_batch_export, create_batch_export_ok
from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user


from posthog.temporal.client import sync_connect


pytestmark = [
    pytest.mark.django_db,
]


def test_batch_export_backfill(client: HttpClient):
    """
    We should be able to create a Batch Export, then request that there should
    be a run created for an arbitrary date range in the past.
    """
    temporal = sync_connect()

    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": "my-production-s3-bucket",
            "region": "us-east-1",
            "key_template": "posthog-events/{table_name}.csv",
            "batch_window_size": 3600,
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
        batch_export = create_batch_export_ok(client, team.pk, batch_export_data)

        batch_export_id = batch_export["id"]

        response = backfill_batch_export(client, team.pk, batch_export_id, "2021-01-01T00:00:00", "2021-01-01T01:00:00")

        assert response.status_code == status.HTTP_200_OK, response.json()


def test_cannot_trigger_backfill_for_another_organization(client: HttpClient):
    temporal = sync_connect()

    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": "my-production-s3-bucket",
            "region": "us-east-1",
            "key_template": "posthog-events/{table_name}.csv",
            "batch_window_size": 3600,
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

    other_organization = create_organization("Other Org")
    create_team(other_organization)
    other_user = create_user("other-test@user.com", "Other Test User", other_organization)

    with start_test_worker(temporal):
        client.force_login(user)
        batch_export = create_batch_export_ok(client, team.pk, batch_export_data)

        batch_export_id = batch_export["id"]

        client.force_login(other_user)
        response = backfill_batch_export(client, team.pk, batch_export_id, "2021-01-01T00:00:00", "2021-01-01T01:00:00")

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()


def test_backfill_is_partitioned_by_team_id(client: HttpClient):
    temporal = sync_connect()

    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": "my-production-s3-bucket",
            "region": "us-east-1",
            "key_template": "posthog-events/{table_name}.csv",
            "batch_window_size": 3600,
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
    other_team = create_team(organization)
    user = create_user("test@user.com", "Test User", organization)

    with start_test_worker(temporal):
        client.force_login(user)
        batch_export = create_batch_export_ok(client, team.pk, batch_export_data)

        batch_export_id = batch_export["id"]

        response = backfill_batch_export(
            client, other_team.pk, batch_export_id, "2021-01-01T00:00:00", "2021-01-01T01:00:00"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.json()
