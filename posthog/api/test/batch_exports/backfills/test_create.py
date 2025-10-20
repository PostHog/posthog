import datetime as dt

import pytest
from freezegun import freeze_time
from posthog.test.base import _create_event
from unittest.mock import ANY, patch

from django.test.client import Client as HttpClient

from rest_framework import status

from posthog.api.test.batch_exports.operations import backfill_batch_export, create_batch_export_ok
from posthog.models.person.util import create_person

pytestmark = [
    pytest.mark.django_db,
]


@pytest.mark.parametrize("legacy_endpoint", [False, True])
@pytest.mark.parametrize("model", ["events", "persons"])
def test_batch_export_backfill(client: HttpClient, organization, team, user, temporal, model, legacy_endpoint: bool):
    """Test a BatchExport can be backfilled.

    We should be able to create a Batch Export, then request that the Schedule
    handles backfilling all runs between two dates.

    We currently have two endpoints for creating backfills:
    - /api/projects/{team_id}/batch_exports/{batch_export_id}/backfills (new)
    - /api/projects/{team_id}/batch_exports/{batch_export_id}/backfill (old, deprecated)

    This test checks that both endpoints work as expected.
    We can remove the legacy endpoint once we're confident that nobody is using it.
    """
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
        "model": model,
    }

    client.force_login(user)

    # ensure there is data to backfill, otherwise validation will fail
    if model == "events":
        _create_event(
            team=team,
            event="$pageview",
            distinct_id="person_1",
            timestamp=dt.datetime(2021, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
        )
    else:
        create_person(
            team_id=team.pk,
            properties={"distinct_id": "1"},
            uuid=None,
            version=0,
            timestamp=dt.datetime(2021, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
        )

    batch_export = create_batch_export_ok(client, team.pk, batch_export_data)
    batch_export_id = batch_export["id"]

    response = backfill_batch_export(
        client=client,
        team_id=team.pk,
        batch_export_id=batch_export_id,
        start_at="2021-01-01T00:00:00+00:00",
        end_at="2021-01-01T01:00:00+00:00",
        legacy_endpoint=legacy_endpoint,
    )
    assert response.status_code == status.HTTP_200_OK, response.json()


def test_batch_export_backfill_with_non_isoformatted_dates(client: HttpClient, organization, team, user, temporal):
    """Test a BatchExport backfill fails if we pass malformed dates."""
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

    client.force_login(user)

    batch_export = create_batch_export_ok(client, team.pk, batch_export_data)

    batch_export_id = batch_export["id"]

    response = backfill_batch_export(client, team.pk, batch_export_id, "not a date", "2021-01-01T01:00:00+00:00")
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    response = backfill_batch_export(client, team.pk, batch_export_id, "2021-01-01T01:00:00+00:00", "not a date")
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()


def test_batch_export_backfill_with_end_at_in_the_future(client: HttpClient, organization, team, user, temporal):
    """Test a BatchExport backfill fails if we pass malformed dates."""
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
        "model": "events",
    }

    test_time = dt.datetime.now(dt.UTC)
    client.force_login(user)

    # ensure there is data to backfill, otherwise validation will fail
    _create_event(
        team=team,
        event="$pageview",
        distinct_id="person_1",
        timestamp=test_time + dt.timedelta(minutes=10),
    )

    batch_export = create_batch_export_ok(client, team.pk, batch_export_data)

    batch_export_id = batch_export["id"]

    with freeze_time(test_time):
        response = backfill_batch_export(
            client,
            team.pk,
            batch_export_id,
            (test_time - dt.timedelta(minutes=30)).isoformat(),
            (test_time + dt.timedelta(minutes=30)).isoformat(),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "is in the future" in response.json()["detail"]


def test_batch_export_backfill_with_naive_bounds(client: HttpClient, organization, team, user, temporal):
    """Test a BatchExport backfill fails if we naive dates."""
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

    client.force_login(user)

    batch_export = create_batch_export_ok(client, team.pk, batch_export_data)

    batch_export_id = batch_export["id"]

    response = backfill_batch_export(client, team.pk, batch_export_id, "2021-01-01T01:00:00", "2021-01-01T01:00:00")
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    response = backfill_batch_export(client, team.pk, batch_export_id, "2021-01-01T01:00:00", "2021-01-01T01:00:00")
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()


def test_batch_export_backfill_with_start_at_after_end_at(client: HttpClient, organization, team, user, temporal):
    """Test a BatchExport backfill fails if start_at is after end_at."""
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

    client.force_login(user)

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


def test_cannot_trigger_backfill_for_another_organization(client: HttpClient, temporal, organization, team, user):
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

    from posthog.api.test.batch_exports.fixtures import create_organization
    from posthog.api.test.test_team import create_team
    from posthog.api.test.test_user import create_user

    other_organization = create_organization("Other Org")
    create_team(other_organization)
    other_user = create_user("other-test@user.com", "Other Test User", other_organization)

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


def test_backfill_is_partitioned_by_team_id(client: HttpClient, temporal, organization, team, user):
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

    from posthog.api.test.test_team import create_team

    other_team = create_team(organization)

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


def test_batch_export_backfill_created_in_timezone(client: HttpClient, temporal, organization, user):
    """Test creating a BatchExportBackfill sets the right ID in UTC timezone.

    PostgreSQL stores datetime values in their UTC representation, converting the input
    if it's in a different timezone. For this reason, we need backfills to have a workflow
    ID in UTC representation, so that we can later re-construct this ID from the data stored
    in PostgreSQL.

    Otherwise, we would need to store a timezone field in PostgreSQL too. We may want
    to do that later, but this test case is still valuable to ensure we are pulling and
    using the timezone stored in PostgreSQL correctly.
    """

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

    from posthog.api.test.test_team import create_team

    team = create_team(organization, timezone="US/Eastern")
    client.force_login(user)

    # ensure there is data to backfill, otherwise validation will fail
    _create_event(
        team=team, event="$pageview", distinct_id="person_1", timestamp=dt.datetime(2021, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
    )

    batch_export = create_batch_export_ok(client, team.pk, batch_export_data)
    batch_export_id = batch_export["id"]

    response = backfill_batch_export(
        client,
        team.pk,
        batch_export_id,
        "2021-01-01T00:00:00-05:00",
        "2021-10-01T00:00:00-04:00",
    )

    data = response.json()

    assert response.status_code == status.HTTP_200_OK, data
    assert data["backfill_id"] == f"{batch_export_id}-Backfill-2021-01-01T05:00:00+00:00-2021-10-01T04:00:00+00:00"


@pytest.mark.parametrize("model", ["events", "persons"])
def test_batch_export_backfill_when_start_at_is_before_earliest_backfill_start_at(
    client: HttpClient, organization, team, user, temporal, model
):
    """Test that a BatchExport backfill will use the earliest possible backfill start date if start_at is before this.

    For example if the timestamp of the earliest event is 2021-01-02T00:10:00+00:00, and the BatchExport is created with
    a start_at of 2021-01-01T00:00:00+00:00, then the backfill will use 2021-01-02T00:00:00+00:00 as the start_at date.
    """
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
        "interval": "day",
        "model": model,
    }

    client.force_login(user)

    if model == "events":
        _create_event(
            team=team,
            event="$pageview",
            distinct_id="person_1",
            timestamp=dt.datetime(2021, 1, 2, 0, 10, 0, tzinfo=dt.UTC),
        )
    else:
        create_person(
            team_id=team.pk,
            properties={"distinct_id": "1"},
            uuid=None,
            version=0,
            timestamp=dt.datetime(2021, 1, 2, 0, 10, 0, tzinfo=dt.UTC),
        )

    batch_export = create_batch_export_ok(client, team.pk, batch_export_data)
    batch_export_id = batch_export["id"]
    with patch("posthog.batch_exports.http.backfill_export", return_value=batch_export_id) as mock_backfill_export:
        response = backfill_batch_export(
            client,
            team.pk,
            batch_export_id,
            "2021-01-01T00:00:00+00:00",
            "2021-01-03T00:00:00+00:00",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()

        mock_backfill_export.assert_called_with(
            ANY,  # temporal instance will be a different object
            batch_export_id,
            team.pk,
            dt.datetime.fromisoformat("2021-01-02T00:00:00+00:00").astimezone(team.timezone_info),
            dt.datetime.fromisoformat("2021-01-03T00:00:00+00:00").astimezone(team.timezone_info),
        )


def test_batch_export_backfill_when_backfill_end_at_is_before_earliest_event(
    client: HttpClient, organization, team, user, temporal
):
    """Test a BatchExport backfill fails if the end_at is before the earliest event.

    In this case, we know that the backfill range doesn't contain any data, so we can fail fast.

    For example if the timestamp of the earliest event is 2021-01-03T00:10:00+00:00, and the BatchExport is created with a
    start_at of 2021-01-01T00:00:00+00:00 and an end_at of 2021-01-02T00:00:00+00:00, then the backfill will fail.
    """
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
        "interval": "day",
    }

    client.force_login(user)

    _create_event(
        team=team, event="$pageview", distinct_id="person_1", timestamp=dt.datetime(2021, 1, 3, 0, 10, 0, tzinfo=dt.UTC)
    )
    batch_export = create_batch_export_ok(client, team.pk, batch_export_data)
    batch_export_id = batch_export["id"]
    with patch("posthog.batch_exports.http.backfill_export", return_value=batch_export_id):
        response = backfill_batch_export(
            client,
            team.pk,
            batch_export_id,
            "2021-01-01T00:00:00+00:00",
            "2021-01-02T00:00:00+00:00",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert (
            response.json()["detail"]
            == "The provided backfill date range contains no data. The earliest possible backfill start date is 2021-01-03 00:00:00"
        )


@pytest.mark.parametrize("model", ["events", "persons"])
def test_batch_export_backfill_when_no_data_exists(client: HttpClient, organization, team, user, temporal, model):
    """Test a BatchExport backfill fails if no data exists for the given model."""
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
        "interval": "day",
        "model": model,
    }

    client.force_login(user)

    batch_export = create_batch_export_ok(client, team.pk, batch_export_data)
    batch_export_id = batch_export["id"]
    with patch("posthog.batch_exports.http.backfill_export", return_value=batch_export_id):
        response = backfill_batch_export(
            client,
            team.pk,
            batch_export_id,
            "2021-01-01T00:00:00+00:00",
            "2021-01-02T00:00:00+00:00",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["detail"] == "There is no data to backfill for this model."
