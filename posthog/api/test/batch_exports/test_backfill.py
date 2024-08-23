import datetime as dt

import pytest
from django.test.client import Client as HttpClient
from freezegun import freeze_time
from rest_framework import status

from posthog.api.test.batch_exports.conftest import start_test_worker
from posthog.api.test.batch_exports.operations import (
    backfill_batch_export,
    create_batch_export_ok,
)
from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.temporal.common.client import sync_connect

pytestmark = [
    pytest.mark.django_db,
]


def test_batch_export_backfill(client: HttpClient):
    """Test a BatchExport can be backfilled.

    We should be able to create a Batch Export, then request that the Schedule
    handles backfilling all runs between two dates.
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
        batch_export = create_batch_export_ok(client, team.pk, batch_export_data)
        batch_export_id = batch_export["id"]

        response = backfill_batch_export(
            client,
            team.pk,
            batch_export_id,
            "2021-01-01T00:00:00+00:00",
            "2021-01-01T01:00:00+00:00",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()


def test_batch_export_backfill_with_non_isoformatted_dates(client: HttpClient):
    """Test a BatchExport backfill fails if we pass malformed dates."""
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
        batch_export = create_batch_export_ok(client, team.pk, batch_export_data)

        batch_export_id = batch_export["id"]

        response = backfill_batch_export(client, team.pk, batch_export_id, "not a date", "2021-01-01T01:00:00+00:00")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

        response = backfill_batch_export(client, team.pk, batch_export_id, "2021-01-01T01:00:00+00:00", "not a date")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()


def test_batch_export_backfill_with_end_at_in_the_future(client: HttpClient):
    """Test a BatchExport backfill fails if we pass malformed dates."""
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
    test_time = dt.datetime.now(dt.UTC)
    client.force_login(user)

    with start_test_worker(temporal):
        batch_export = create_batch_export_ok(client, team.pk, batch_export_data)

        batch_export_id = batch_export["id"]

        with freeze_time(test_time):
            response = backfill_batch_export(
                client,
                team.pk,
                batch_export_id,
                test_time.isoformat(),
                (test_time + dt.timedelta(hours=1, seconds=1)).isoformat(),
            )
            assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()


def test_batch_export_backfill_with_naive_bounds(client: HttpClient):
    """Test a BatchExport backfill fails if we naive dates."""
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
        batch_export = create_batch_export_ok(client, team.pk, batch_export_data)

        batch_export_id = batch_export["id"]

        response = backfill_batch_export(client, team.pk, batch_export_id, "2021-01-01T01:00:00", "2021-01-01T01:00:00")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

        response = backfill_batch_export(client, team.pk, batch_export_id, "2021-01-01T01:00:00", "2021-01-01T01:00:00")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()


def test_batch_export_backfill_with_start_at_after_end_at(client: HttpClient):
    """Test a BatchExport backfill fails if start_at is after end_at."""
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
        batch_export = create_batch_export_ok(client, team.pk, batch_export_data)

        batch_export_id = batch_export["id"]

        response = backfill_batch_export(
            client,
            team.pk,
            batch_export_id,
            "2021-01-01T01:00:00+00:00",
            "2021-01-01T01:00:00+00:00",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

        response = backfill_batch_export(
            client,
            team.pk,
            batch_export_id,
            "2021-01-01T01:00:00+00:00",
            "2020-01-01T01:00:00+00:00",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()


def test_cannot_trigger_backfill_for_another_organization(client: HttpClient):
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

    other_organization = create_organization("Other Org")
    create_team(other_organization)
    other_user = create_user("other-test@user.com", "Other Test User", other_organization)

    with start_test_worker(temporal):
        client.force_login(user)
        batch_export = create_batch_export_ok(client, team.pk, batch_export_data)

        batch_export_id = batch_export["id"]

        client.force_login(other_user)
        response = backfill_batch_export(
            client,
            team.pk,
            batch_export_id,
            "2021-01-01T00:00:00+00:00",
            "2021-01-01T01:00:00+00:00",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()


def test_backfill_is_partitioned_by_team_id(client: HttpClient):
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
    other_team = create_team(organization)
    user = create_user("test@user.com", "Test User", organization)

    with start_test_worker(temporal):
        client.force_login(user)
        batch_export = create_batch_export_ok(client, team.pk, batch_export_data)

        batch_export_id = batch_export["id"]

        response = backfill_batch_export(
            client,
            other_team.pk,
            batch_export_id,
            "2021-01-01T00:00:00+00:00",
            "2021-01-01T01:00:00+00:00",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.json()
