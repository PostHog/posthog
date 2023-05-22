from django.test.client import Client as TestClient
import pytest

from posthog.api.test.batch_exports.conftest import start_test_worker
from posthog.api.test.batch_exports.operations import (
    create_batch_export_ok,
    get_batch_export_ok,
    pause_batch_export,
    pause_batch_export_ok,
    unpause_batch_export,
    unpause_batch_export_ok,
)
from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user


from posthog.batch_exports.service import describe_schedule


from posthog.temporal.client import sync_connect


pytestmark = [
    pytest.mark.django_db,
]


def test_pause_and_unpause_batch_export(client: TestClient):
    """Test pausing and unpausing a BatchExport."""
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
    # We create an empty schedule so nothing will run and we can pause/unpause as much as we want.
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
        batch_export = create_batch_export_ok(
            client,
            team.pk,
            batch_export_data,
        )

        assert batch_export["paused"] is False
        schedule_desc = describe_schedule(temporal, batch_export["id"])
        assert schedule_desc.schedule.state.paused is False

        batch_export_id = batch_export["id"]

        pause_batch_export_ok(client, team.pk, batch_export_id)
        data = get_batch_export_ok(client, team.pk, batch_export_id)

        assert data["paused"] is True
        schedule_desc = describe_schedule(temporal, data["id"])
        assert schedule_desc.schedule.state.paused is True

        unpause_batch_export_ok(client, team.pk, batch_export_id)

        data = get_batch_export_ok(client, team.pk, batch_export_id)

        assert data["paused"] is False
        schedule_desc = describe_schedule(temporal, data["id"])
        assert schedule_desc.schedule.state.paused is False


def test_connot_pause_and_unpause_batch_exports_of_other_organizations(client: TestClient):
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
    # We create an empty schedule so nothing will run and we can pause/unpause as much as we want.
    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    organization = create_organization("Test Org")
    team = create_team(organization)
    user = create_user("test@user.com", "Test User", organization)

    other_organization = create_organization("Other Test Org")
    create_team(other_organization)
    other_user = create_user("another-test@user.com", "Another Test User", other_organization)

    with start_test_worker(temporal):
        client.force_login(user)
        batch_export = create_batch_export_ok(
            client,
            team.pk,
            batch_export_data,
        )

        batch_export_id = batch_export["id"]

        client.force_login(other_user)
        response = pause_batch_export(client, team.pk, batch_export_id)
        assert response.status_code == 403, response.json()

        # Make sure it's still running
        client.force_login(user)
        data = get_batch_export_ok(client, team.pk, batch_export_id)
        assert data["paused"] is False

        schedule_desc = describe_schedule(temporal, data["id"])
        assert schedule_desc.schedule.state.paused is False

        # Now pause it for real, as the correct user
        pause_batch_export_ok(client, team.pk, batch_export_id)

        # Now check we can't unpause it as the other user.
        client.force_login(other_user)
        response = unpause_batch_export(client, team.pk, batch_export_id)
        assert response.status_code == 403, response.json()

        # Make sure it's still paused
        client.force_login(user)
        data = get_batch_export_ok(client, team.pk, batch_export_id)
        assert data["paused"] is True
        schedule_desc = describe_schedule(temporal, data["id"])
        assert schedule_desc.schedule.state.paused is True


def test_pause_and_unpause_are_partitioned_by_team_id(client: TestClient):
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
    # We create an empty schedule so nothing will run and we can pause/unpause as much as we want.
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
        batch_export = create_batch_export_ok(
            client,
            team.pk,
            batch_export_data,
        )

        batch_export_id = batch_export["id"]

        # True pausing using the other team
        response = pause_batch_export(client, other_team.pk, batch_export_id)
        assert response.status_code == 404, response.json()

        # Make sure it's still running
        data = get_batch_export_ok(client, team.pk, batch_export_id)
        assert data["paused"] is False

        schedule_desc = describe_schedule(temporal, data["id"])
        assert schedule_desc.schedule.state.paused is False

        # Now pause it for real, as the correct team
        pause_batch_export_ok(client, team.pk, batch_export_id)

        # Now check we can't unpause it as the other team.
        response = unpause_batch_export(client, other_team.pk, batch_export_id)
        assert response.status_code == 404, response.json()

        # Make sure it's still paused
        data = get_batch_export_ok(client, team.pk, batch_export_id)
        assert data["paused"] is True
        schedule_desc = describe_schedule(temporal, data["id"])
        assert schedule_desc.schedule.state.paused is True
