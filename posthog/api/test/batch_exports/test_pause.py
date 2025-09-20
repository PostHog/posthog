import datetime as dt

import pytest
from unittest.mock import ANY, patch

from django.test.client import Client as HttpClient

from rest_framework import status

from posthog.api.test.batch_exports.operations import (
    create_batch_export_ok,
    get_batch_export_ok,
    pause_batch_export,
    pause_batch_export_ok,
    unpause_batch_export,
    unpause_batch_export_ok,
)
from posthog.batch_exports.service import batch_export_delete_schedule
from posthog.temporal.common.schedule import describe_schedule

pytestmark = [
    pytest.mark.django_db,
]


def test_pause_and_unpause_batch_export(client: HttpClient, temporal, organization, team, user):
    """Test pausing and unpausing a BatchExport."""

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
    # We create an empty schedule so nothing will run and we can pause/unpause as much as we want.
    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)
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


def test_cannot_pause_and_unpause_batch_exports_of_other_organizations(
    client: HttpClient, temporal, organization, team, user
):
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
    # We create an empty schedule so nothing will run and we can pause/unpause as much as we want.
    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    from posthog.api.test.batch_exports.fixtures import create_organization
    from posthog.api.test.test_team import create_team
    from posthog.api.test.test_user import create_user

    other_organization = create_organization("Other Test Org")
    create_team(other_organization)
    other_user = create_user("another-test@user.com", "Another Test User", other_organization)
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


def test_pause_and_unpause_are_partitioned_by_team_id(client: HttpClient, temporal, organization, team, user):
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
    # We create an empty schedule so nothing will run and we can pause/unpause as much as we want.
    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    from posthog.api.test.test_team import create_team

    other_team = create_team(organization)
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


def test_pause_batch_export_that_is_already_paused(client: HttpClient, temporal, organization, team, user):
    """Test pausing a BatchExport that is already paused doesn't actually do anything."""

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
    # We create an empty schedule so nothing will run and we can pause/unpause as much as we want.
    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)
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

    last_updated_at = data["last_updated_at"]

    assert last_updated_at > batch_export["last_updated_at"]
    assert data["paused"] is True
    schedule_desc = describe_schedule(temporal, data["id"])
    assert schedule_desc.schedule.state.paused is True

    pause_batch_export_ok(client, team.pk, batch_export_id)
    data = get_batch_export_ok(client, team.pk, batch_export_id)

    assert last_updated_at == data["last_updated_at"]


def test_unpause_batch_export_that_is_already_unpaused(client: HttpClient, temporal, organization, team, user):
    """Test unpausing a BatchExport that is already unpaused doesn't actually do anything."""

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
    # We create an empty schedule so nothing will run and we can pause/unpause as much as we want.
    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)
    batch_export = create_batch_export_ok(
        client,
        team.pk,
        batch_export_data,
    )

    assert batch_export["paused"] is False
    schedule_desc = describe_schedule(temporal, batch_export["id"])
    assert schedule_desc.schedule.state.paused is False

    batch_export_id = batch_export["id"]
    last_updated_at = batch_export["last_updated_at"]

    unpause_batch_export_ok(client, team.pk, batch_export_id)
    data = get_batch_export_ok(client, team.pk, batch_export_id)

    assert last_updated_at == data["last_updated_at"]


def test_pause_non_existent_batch_export(client: HttpClient, temporal, organization, team, user):
    """Test pausing a BatchExport that doesn't exist."""

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
    # We create an empty schedule so nothing will run and we can pause/unpause as much as we want.
    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)
    batch_export = create_batch_export_ok(
        client,
        team.pk,
        batch_export_data,
    )

    assert batch_export["paused"] is False
    schedule_desc = describe_schedule(temporal, batch_export["id"])
    assert schedule_desc.schedule.state.paused is False

    batch_export_delete_schedule(temporal, batch_export["id"])

    batch_export_id = batch_export["id"]
    resp = pause_batch_export(client, team.pk, batch_export_id)
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


def test_unpause_can_trigger_a_backfill(client: HttpClient, temporal, organization, team, user):
    """Test unpausing a BatchExport can trigger a backfill."""

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
    # We create an empty schedule so nothing will run and we can pause/unpause as much as we want.
    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)
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

    with patch("posthog.batch_exports.service.backfill_export") as mock_backfill:
        unpause_batch_export_ok(client, team.pk, batch_export_id, backfill=True)

    data = get_batch_export_ok(client, team.pk, batch_export_id)
    assert batch_export["last_updated_at"] < data["last_updated_at"]
    start_at = dt.datetime.strptime(data["last_paused_at"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=dt.UTC)
    end_at = dt.datetime.strptime(data["last_updated_at"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=dt.UTC)
    mock_backfill.assert_called_once_with(
        ANY,
        batch_export["id"],
        team.pk,
        start_at,
        end_at,
    )
