import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time
from posthog.test.base import _create_event
from unittest.mock import ANY, patch

from django.test.client import Client as HttpClient

from rest_framework import status

from posthog.api.test.batch_exports.operations import backfill_batch_export, create_batch_export_ok
from posthog.models.person.util import create_person
from posthog.models.team import Team

pytestmark = [
    pytest.mark.django_db,
]


def _create_batch_export_ok(
    client: HttpClient,
    team: Team,
    model: str,
    interval: str = "hour",
    timezone: str = "UTC",
    offset_day: int | None = None,
    offset_hour: int | None = None,
):
    """Helper function to create a BatchExport."""
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
        "interval": interval,
        "timezone": timezone,
        "offset_day": offset_day,
        "offset_hour": offset_hour,
        "model": model,
    }
    return create_batch_export_ok(client, team.pk, batch_export_data)


def _get_expected_backfill_workflow_id(
    batch_export_id: str, start_date: str, end_date: str, timezone: str, offset_hour: int | None = None
) -> str:
    """Helper function to calculate the expected backfill workflow ID.

    Note that we always convert to UTC for the workflow ID.
    """
    start_date_obj = dt.date.fromisoformat(start_date)
    end_date_obj = dt.date.fromisoformat(end_date)
    expected_start_at = dt.datetime.combine(start_date_obj, dt.time(offset_hour or 0, 0, 0)).replace(
        tzinfo=ZoneInfo(timezone)
    )
    expected_start_at_utc = expected_start_at.astimezone(dt.UTC).isoformat()
    expected_end_at = dt.datetime.combine(end_date_obj, dt.time(offset_hour or 0, 0, 0)).replace(
        tzinfo=ZoneInfo(timezone)
    )
    expected_end_at_utc = expected_end_at.astimezone(dt.UTC).isoformat()
    return f"{batch_export_id}-Backfill-{expected_start_at_utc}-{expected_end_at_utc}"


@pytest.mark.parametrize("model", ["events", "persons"])
def test_batch_export_backfill_success(client: HttpClient, organization, team, user, temporal, model):
    """Test a BatchExport can be backfilled.

    We should be able to create a Batch Export, then request that the Schedule
    handles backfilling all runs between two dates.
    """

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

    batch_export = _create_batch_export_ok(client, team, model)
    batch_export_id = batch_export["id"]

    response = backfill_batch_export(
        client=client,
        team_id=team.pk,
        batch_export_id=batch_export_id,
        start_at="2021-01-01T00:00:00+00:00",
        end_at="2021-01-01T01:00:00+00:00",
    )
    assert response.status_code == status.HTTP_200_OK, response.json()


@pytest.mark.parametrize(
    "timezone,offset_hour",
    [
        ("UTC", None),
        ("US/Pacific", 1),
        ("Asia/Kathmandu", 20),
    ],
)
def test_batch_export_backfill_for_daily_schedule(
    client: HttpClient, organization, team, user, temporal, timezone, offset_hour
):
    """Test a BatchExport with a daily schedule can be backfilled.

    For daily schedules, the start and end dates should just be a date string rather than a datetime string.
    """

    client.force_login(user)

    # ensure there is data to backfill, otherwise validation will fail
    _create_event(
        team=team,
        event="$pageview",
        distinct_id="person_1",
        timestamp=dt.datetime(2026, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
    )

    batch_export = _create_batch_export_ok(client, team, "events", "day", timezone, None, offset_hour)
    batch_export_id = batch_export["id"]

    response = backfill_batch_export(
        client=client,
        team_id=team.pk,
        batch_export_id=batch_export_id,
        start_at="2026-01-01",
        end_at="2026-01-02",
    )
    assert response.status_code == status.HTTP_200_OK, response.json()

    expected_workflow_id = _get_expected_backfill_workflow_id(
        batch_export_id, "2026-01-01", "2026-01-02", timezone, offset_hour
    )
    assert response.json()["backfill_id"] == expected_workflow_id


def test_batch_export_backfill_for_daily_schedule_with_datetime_strings_fails(
    client: HttpClient, organization, team, user, temporal
):
    """Test a BatchExport with a daily schedule fails if we pass datetime strings.

    It is more intuitive to pass in date strings rather than datetime strings for daily schedules, especially when the
    schedule might not necessarily run at midnight.
    """

    client.force_login(user)

    batch_export = _create_batch_export_ok(client, team, "events", "day")
    batch_export_id = batch_export["id"]

    response = backfill_batch_export(
        client=client,
        team_id=team.pk,
        batch_export_id=batch_export_id,
        start_at="2021-01-01T00:00:00+00:00",
        end_at="2021-01-01T01:00:00+00:00",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert response.json()["detail"] == (
        "Input '2021-01-01T00:00:00+00:00' is not a valid ISO formatted date. "
        "Daily or weekly batch export backfills expect only the date component, but a time was included."
    )


@pytest.mark.parametrize(
    "timezone,offset_day,offset_hour",
    [
        ("UTC", 0, None),  # Sunday, midnight
        ("US/Pacific", 0, 1),  # Sunday, 1am
        ("Asia/Kathmandu", 3, 20),  # Wednesday, 8pm
    ],
)
def test_batch_export_backfill_for_weekly_schedule(
    client: HttpClient, organization, team, user, temporal, timezone, offset_day, offset_hour
):
    """Test a BatchExport with a weekly schedule can be backfilled.

    For weekly schedules, the start and end dates should just be a date string rather than a datetime string.
    The date must be on the correct day of the week according to the batch export's offset_day.
    """
    client.force_login(user)

    # ensure there is data to backfill, otherwise validation will fail
    # Use dates that match the offset_day: Jan 4, 2026 is a Sunday (offset_day=0), Jan 7, 2026 is a Wednesday (offset_day=3)
    if offset_day == 0:
        event_date = dt.datetime(2026, 1, 4, 0, 0, 0, tzinfo=dt.UTC)  # Sunday
        start_date = "2026-01-04"  # Sunday
        end_date = "2026-01-11"  # Sunday
    else:  # offset_day == 3 (Wednesday)
        event_date = dt.datetime(2026, 1, 7, 0, 0, 0, tzinfo=dt.UTC)  # Wednesday
        start_date = "2026-01-07"  # Wednesday
        end_date = "2026-01-14"  # Wednesday

    _create_event(
        team=team,
        event="$pageview",
        distinct_id="person_1",
        timestamp=event_date,
    )

    batch_export = _create_batch_export_ok(client, team, "events", "week", timezone, offset_day, offset_hour)
    batch_export_id = batch_export["id"]

    response = backfill_batch_export(
        client=client,
        team_id=team.pk,
        batch_export_id=batch_export_id,
        start_at=start_date,
        end_at=end_date,
    )
    assert response.status_code == status.HTTP_200_OK, response.json()

    expected_workflow_id = _get_expected_backfill_workflow_id(
        batch_export_id, start_date, end_date, timezone, offset_hour
    )
    assert response.json()["backfill_id"] == expected_workflow_id


def test_batch_export_backfill_for_weekly_schedule_with_datetime_strings_fails(
    client: HttpClient, organization, team, user, temporal
):
    """Test a BatchExport with a weekly schedule fails if we pass datetime strings.

    It is more intuitive to pass in date strings rather than datetime strings for weekly schedules, especially when the
    schedule might not necessarily run at midnight.
    """

    client.force_login(user)

    batch_export = _create_batch_export_ok(client, team, "events", "week", "UTC", 0, 0)
    batch_export_id = batch_export["id"]

    response = backfill_batch_export(
        client=client,
        team_id=team.pk,
        batch_export_id=batch_export_id,
        start_at="2026-01-04T00:00:00+00:00",
        end_at="2026-01-11T00:00:00+00:00",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert response.json()["detail"] == (
        "Input '2026-01-04T00:00:00+00:00' is not a valid ISO formatted date. "
        "Daily or weekly batch export backfills expect only the date component, but a time was included."
    )


def test_batch_export_backfill_for_weekly_schedule_fails_if_day_of_week_is_incorrect(
    client: HttpClient, organization, team, user, temporal
):
    """Test a BatchExport with a weekly schedule fails if we pass a date that is not on the correct day of the week.

    In this example, we are passing a start date of a Sunday, but the batch export is configured to run weekly on Monday.
    """

    client.force_login(user)

    # use an offset day of 1, so we run weekly on Monday
    batch_export = _create_batch_export_ok(client, team, "events", "week", "UTC", 1, None)
    batch_export_id = batch_export["id"]

    response = backfill_batch_export(
        client=client,
        team_id=team.pk,
        batch_export_id=batch_export_id,
        start_at="2026-01-04",  # this is a Sunday
        end_at="2026-01-11",  # this is a Sunday
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert response.json()["detail"] == (
        "Input 2026-01-04 is not on the correct day of the week for this batch export. "
        "2026-01-04 is a Sunday but this batch export is configured to run weekly on Monday."
    )


def test_batch_export_backfill_with_non_isoformatted_dates(client: HttpClient, organization, team, user, temporal):
    """Test a BatchExport backfill fails if we pass malformed dates."""

    client.force_login(user)

    batch_export = _create_batch_export_ok(client, team, "events")

    batch_export_id = batch_export["id"]

    response = backfill_batch_export(client, team.pk, batch_export_id, "not a date", "2021-01-01T01:00:00+00:00")
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    response = backfill_batch_export(client, team.pk, batch_export_id, "2021-01-01T01:00:00+00:00", "not a date")
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()


def test_batch_export_backfill_with_end_at_in_the_future(client: HttpClient, organization, team, user, temporal):
    """Test a BatchExport backfill fails if we pass malformed dates."""

    test_time = dt.datetime.now(dt.UTC)
    client.force_login(user)

    # ensure there is data to backfill, otherwise validation will fail
    _create_event(
        team=team,
        event="$pageview",
        distinct_id="person_1",
        timestamp=test_time + dt.timedelta(minutes=10),
    )

    batch_export = _create_batch_export_ok(client, team, "events")

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

    client.force_login(user)
    batch_export = _create_batch_export_ok(client, team, "events")

    batch_export_id = batch_export["id"]

    response = backfill_batch_export(client, team.pk, batch_export_id, "2021-01-01T01:00:00", "2021-01-01T01:00:00")
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    response = backfill_batch_export(client, team.pk, batch_export_id, "2021-01-01T01:00:00", "2021-01-01T01:00:00")
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()


def test_batch_export_backfill_with_start_at_after_end_at(client: HttpClient, organization, team, user, temporal):
    """Test a BatchExport backfill fails if start_at is after end_at."""

    client.force_login(user)

    batch_export = _create_batch_export_ok(client, team, "events")
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
    from posthog.api.test.batch_exports.fixtures import create_organization
    from posthog.api.test.test_team import create_team
    from posthog.api.test.test_user import create_user

    other_organization = create_organization("Other Org")
    create_team(other_organization)
    other_user = create_user("other-test@user.com", "Other Test User", other_organization)

    client.force_login(user)
    batch_export = _create_batch_export_ok(client, team, "events")

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
    from posthog.api.test.test_team import create_team

    other_team = create_team(organization)

    client.force_login(user)

    batch_export = _create_batch_export_ok(client, team, "events")
    batch_export_id = batch_export["id"]

    response = backfill_batch_export(
        client,
        other_team.pk,
        batch_export_id,
        "2021-01-01T00:00:00+00:00",
        "2021-01-01T01:00:00+00:00",
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.json()


def test_batch_export_backfill_created_in_timezone(client: HttpClient, temporal, organization, user, team):
    """Test creating a BatchExportBackfill sets the right ID in UTC timezone.

    PostgreSQL stores datetime values in their UTC representation, converting the input
    if it's in a different timezone. For this reason, we need backfills to have a workflow
    ID in UTC representation, so that we can later re-construct this ID from the data stored
    in PostgreSQL.

    Otherwise, we would need to store a timezone field in PostgreSQL too. We may want
    to do that later, but this test case is still valuable to ensure we are pulling and
    using the timezone stored in PostgreSQL correctly.
    """

    client.force_login(user)

    # ensure there is data to backfill, otherwise validation will fail
    _create_event(
        team=team, event="$pageview", distinct_id="person_1", timestamp=dt.datetime(2021, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
    )

    batch_export = _create_batch_export_ok(client, team, "events")
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

    batch_export = _create_batch_export_ok(client, team, model)
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

    client.force_login(user)

    _create_event(
        team=team, event="$pageview", distinct_id="person_1", timestamp=dt.datetime(2021, 1, 3, 0, 10, 0, tzinfo=dt.UTC)
    )
    batch_export = _create_batch_export_ok(client, team, "events")
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

    client.force_login(user)

    batch_export = _create_batch_export_ok(client, team, model)
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
