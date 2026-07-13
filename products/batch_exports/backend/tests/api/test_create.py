import json
import typing as t
import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from unittest import mock

from django.test import override_settings
from django.test.client import Client as HttpClient

from asgiref.sync import async_to_sync
from rest_framework import status

from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.models.integration import Integration

from products.batch_exports.backend.models.batch_export import BatchExport
from products.batch_exports.backend.tests.api.conftest import (
    assert_is_daily_schedule,
    assert_is_weekly_schedule,
    describe_schedule,
)
from products.batch_exports.backend.tests.api.fixtures import create_organization
from products.batch_exports.backend.tests.api.operations import create_batch_export

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("temporal_worker", "cleanup"),
]


# This file holds generic / cross-destination create tests. Per-destination
# tests live alongside in `test_create_<destination>.py`.


def test_create_batch_export_with_interval_schedule(
    client: HttpClient, temporal, encryption_codec, organization, team, user
):
    """Test creating a BatchExport.

    When creating a BatchExport, we should create a corresponding Schedule in
    Temporal as described by the associated BatchExportSchedule model. In this
    test we assert this Schedule is created in Temporal and populated with the
    expected inputs.
    """

    interval = "hour"

    destination_data = {
        "type": "S3Compatible",
        "config": {
            "bucket_name": "my-production-s3-bucket",
            "region": "us-east-1",
            "prefix": "posthog-events/",
            "aws_access_key_id": "abc123",
            "aws_secret_access_key": "secret",
            "endpoint_url": "https://localhost:9000",
            "use_virtual_style_addressing": True,
        },
        "integration": None,
    }

    batch_export_data: dict[str, t.Any] = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": interval,
    }

    client.force_login(user)

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
        "interval": interval,
    }

    # validate the underlying temporal schedule has been created
    schedule = describe_schedule(temporal, data["id"])

    batch_export = BatchExport.objects.get(id=data["id"])
    assert schedule.schedule.spec.intervals[0].every == batch_export.interval_time_delta
    assert schedule.schedule.spec.jitter == batch_export.jitter

    decoded_payload = async_to_sync(encryption_codec.decode)(schedule.schedule.action.args)
    args = json.loads(decoded_payload[0].data)

    # Common inputs
    assert args["team_id"] == team.pk
    assert args["batch_export_id"] == data["id"]
    assert args["interval"] == interval

    # expected jitter is 15 minutes for hourly exports
    assert batch_export.jitter == dt.timedelta(minutes=15)

    # S3 specific inputs
    assert args["bucket_name"] == "my-production-s3-bucket"
    assert args["region"] == "us-east-1"
    assert args["prefix"] == "posthog-events/"
    assert args["aws_access_key_id"] == "abc123"
    assert args["aws_secret_access_key"] == "secret"
    assert args["use_virtual_style_addressing"]


@pytest.mark.parametrize(
    "interval,timezone,offset_day,offset_hour,expected_interval_offset",
    [
        ("every 5 minutes", None, None, None, None),
        ("hour", "UTC", None, None, None),
        ("hour", "invalid", None, None, None),  # should return an error as invalid timezone is not valid
        ("hour", "US/Pacific", None, None, None),
        ("hour", "US/Pacific", None, 2, None),  # should return an error as offset hour not valid for hourly exports
        ("day", "US/Pacific", None, None, None),  # should run at midnight US/Pacific time
        ("day", "US/Pacific", None, 0, 0),  # should also run at midnight US/Pacific time
        ("day", "Asia/Kathmandu", None, 2, 7200),  # should run at 2am Asia/Kathmandu time
        (
            "day",
            "Asia/Kathmandu",
            None,
            24,
            None,
        ),  # should return an error as 24 is not a valid offset hour for daily exports
        (
            "day",
            "Asia/Kathmandu",
            1,
            6,
            None,
        ),  # should return an error as non-None offset day is not valid for daily exports
        ("week", None, None, None, None),  # should run at midnight on Sunday UTC
        ("week", "Asia/Kathmandu", None, None, None),  # should run at midnight on Sunday Asia/Kathmandu time
        ("week", "Asia/Kathmandu", 0, 0, 0),  # should also run at midnight on Sunday Asia/Kathmandu time
        ("week", "Europe/Berlin", 1, 2, 93600),  # should run at 2am on Monday Europe/Berlin time (1 days + 2 hours)
        (
            "week",
            "Europe/Berlin",
            7,
            2,
            None,
        ),  # should return an error as 7 is not a valid offset day for weekly exports
    ],
)
def test_create_batch_export_with_different_intervals_timezones_and_interval_offsets(
    client: HttpClient,
    interval: str,
    timezone: str,
    offset_day: int | None,
    offset_hour: int | None,
    expected_interval_offset: int,
    temporal,
    organization,
):
    """Test creating a BatchExport with different intervals, timezones and interval offsets.

    A user should be able to create a BatchExport in the timezone of their choice, and set an offset to run it
    at a different time.  For example they could create a daily export at 1am US/Pacific time by setting timezone and
    the offset_hour to 1.

    For intervals other than daily or weekly, the timezone and offset have no effect.

    When creating a BatchExport, we should create a corresponding Schedule in Temporal as described by the associated
    BatchExport model. In this test we assert this Schedule is created in Temporal with the expected timezone and
    offset. We check the upcoming runs to confirm these look correct based on this information.
    """

    destination_data = {
        "type": "AwsS3",
        "config": {
            "bucket_name": "my-production-s3-bucket",
            "region": "us-east-1",
            "prefix": "posthog-events/",
            "aws_access_key_id": "abc123",
            "aws_secret_access_key": "secret",
        },
    }

    batch_export_data: dict[str, t.Any] = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": interval,
        "timezone": timezone,
    }

    if offset_hour is not None:
        batch_export_data["offset_hour"] = offset_hour
    if offset_day is not None:
        batch_export_data["offset_day"] = offset_day

    # create a team with a timezone different to the one we are testing to ensure this has no effect on the batch export
    team = create_team(organization, timezone="Asia/Seoul")
    user = create_user("test@user.com", "Test User", organization)
    client.force_login(user)

    # ensure high-frequency-batch-exports feature flag is enabled
    with mock.patch(
        "products.batch_exports.backend.api.batch_export.posthoganalytics.feature_enabled",
        return_value=True,
    ):
        response = create_batch_export(
            client,
            team.pk,
            batch_export_data,
        )

    # if invalid interval offset we should raise a validation error
    expect_error = False
    if offset_day is not None and offset_day > 6:
        expect_error = True
    if offset_hour is not None and offset_hour > 23:
        expect_error = True
    if interval != "day" and interval != "week" and (offset_day is not None or offset_hour is not None):
        expect_error = True
    elif interval == "day" and (offset_day is not None):
        expect_error = True
    elif timezone == "invalid":
        expect_error = True

    if expect_error:
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        return

    assert response.status_code == status.HTTP_201_CREATED, response.json()

    data = response.json()

    schedule = describe_schedule(temporal, data["id"])

    batch_export = BatchExport.objects.get(id=data["id"])
    assert schedule.schedule.spec.jitter == batch_export.jitter
    expected_timezone = timezone if timezone else "UTC"
    assert schedule.schedule.spec.time_zone_name == expected_timezone
    assert batch_export.timezone == expected_timezone
    assert batch_export.interval_offset == expected_interval_offset

    if interval == "hour":
        intervals = schedule.schedule.spec.intervals
        assert len(intervals) == 1
        assert intervals[0].every == dt.timedelta(hours=1)
        assert batch_export.jitter == dt.timedelta(minutes=15)
    elif interval == "every 5 minutes":
        intervals = schedule.schedule.spec.intervals
        assert len(intervals) == 1
        assert intervals[0].every == dt.timedelta(minutes=5)
        assert batch_export.jitter == dt.timedelta(minutes=1)
    elif interval == "day":
        expected_hour = offset_hour if offset_hour is not None else 0
        assert batch_export.offset_hour == expected_hour
        assert data["offset_hour"] == expected_hour
        assert_is_daily_schedule(schedule, expected_hour)
    elif interval == "week":
        expected_day = offset_day if offset_day is not None else 0
        expected_hour = offset_hour if offset_hour is not None else 0
        assert batch_export.offset_day == expected_day
        assert data["offset_day"] == expected_day
        assert batch_export.offset_hour == expected_hour
        assert data["offset_hour"] == expected_hour
        assert_is_weekly_schedule(schedule, expected_day, expected_hour)

    # Assert next run time is what we expect based on the interval and offset
    next_runs = schedule.info.next_action_times
    assert len(next_runs) > 1
    next_run = next_runs[0]
    next_run_2 = next_runs[1]

    # Convert to the schedule's timezone
    tz = ZoneInfo(expected_timezone)
    next_run_local = next_run.astimezone(tz)
    jitter = batch_export.jitter

    # Assert time between runs is roughly the interval time delta.
    # For daily/weekly intervals, DST transitions can shift the UTC difference by up to 1 hour.
    next_run_2_local = next_run_2.astimezone(tz)
    dst_shift = abs((next_run_2_local.utcoffset() or dt.timedelta(0)) - (next_run_local.utcoffset() or dt.timedelta(0)))
    assert abs((next_run_2 - next_run) - batch_export.interval_time_delta) <= jitter + dst_shift

    if interval == "day":
        # For daily exports, check that it runs at the expected hour (based on offset_hour)
        expected_hour = offset_hour if offset_hour is not None else 0
        expected_time = next_run_local.replace(hour=expected_hour, minute=0, second=0, microsecond=0)
        time_diff = abs((next_run_local - expected_time).total_seconds())
        assert time_diff <= jitter.total_seconds(), (
            f"Next run {next_run_local} is at {next_run_local.hour}:{next_run_local.minute}, "
            f"expected {expected_hour}:00 within jitter tolerance of {jitter}"
        )
    elif interval == "week":
        # For weekly exports, check that it runs on the expected day and hour (based on offset_day and offset_hour)
        expected_day = offset_day if offset_day is not None else 0
        expected_hour = offset_hour if offset_hour is not None else 0
        expected_time = next_run_local.replace(hour=expected_hour, minute=0, second=0, microsecond=0)
        time_diff = abs((next_run_local - expected_time).total_seconds())
        # Check day of week (Temporal treats Sunday as 0)
        actual_day = next_run_local.weekday()  # Monday=0, Sunday=6
        # Convert to Temporal's day format (Sunday=0)
        actual_day_temporal = (actual_day + 1) % 7
        # Additional sense check here just to ensure this makes sense
        if expected_interval_offset == 0 or expected_interval_offset == 3600:
            assert actual_day_temporal == 0  # Sunday
        elif expected_interval_offset == 108_000:
            assert actual_day_temporal == 1  # Monday
        assert actual_day_temporal == expected_day, (
            f"Next run {next_run_local} is on day {actual_day_temporal}, expected {expected_day}"
        )
        assert time_diff <= jitter.total_seconds(), (
            f"Next run {next_run_local} is at {next_run_local.hour}:{next_run_local.minute}, "
            f"expected {expected_hour}:00 within jitter tolerance of {jitter}"
        )
    # For hour and "every 5 minutes" intervals, timezone and offset have no effect
    # so we don't need to check for a specific time


def test_cannot_create_a_batch_export_for_another_organization(client: HttpClient, temporal, organization, user):
    destination_data = {
        "type": "AwsS3",
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

    create_team(organization)

    another_organization = create_organization("Another Test Org")
    another_team = create_team(another_organization)

    client.force_login(user)
    response = create_batch_export(
        client,
        another_team.pk,
        batch_export_data,
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()


@pytest.mark.parametrize(
    "destination_type,integration_kind,config",
    [
        ("AwsS3", Integration.IntegrationKind.AWS_S3, {"bucket_name": "b", "region": "us-east-1", "prefix": "p/"}),
        (
            "Databricks",
            Integration.IntegrationKind.DATABRICKS,
            {"http_path": "p", "catalog": "c", "schema": "s", "table_name": "t"},
        ),
    ],
)
def test_cannot_create_batch_export_with_integration_from_another_team(
    client: HttpClient, temporal, organization, team, user, destination_type, integration_kind, config
):
    """The team-scoped `integration` field rejects an integration owned by another team (IDOR).

    This is common to every integration-backed destination — a foreign id reads as "does not exist"
    at field resolution, before any destination-specific validation runs.
    """
    other_team = create_team(organization)
    foreign_integration = Integration.objects.create(
        team=other_team,
        kind=integration_kind,
        integration_id="foreign",
        config={},
        sensitive_config={},
        created_by=user,
    )

    client.force_login(user)
    response = create_batch_export(
        client,
        team.pk,
        {
            "name": "my-export",
            "interval": "hour",
            "destination": {"type": destination_type, "config": config, "integration": foreign_integration.id},
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert response.json()["attr"] == "destination__integration"
    assert response.json()["code"] == "does_not_exist"


def test_cannot_create_a_batch_export_with_higher_frequencies_if_not_enabled(
    client: HttpClient, temporal, organization, team, user
):
    destination_data = {
        "type": "AwsS3",
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
        "interval": "every 5 minutes",
    }

    client.force_login(user)
    with mock.patch(
        "products.batch_exports.backend.api.batch_export.posthoganalytics.feature_enabled",
        return_value=False,
    ) as feature_enabled:
        response = create_batch_export(
            client,
            team.pk,
            batch_export_data,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        feature_enabled.assert_called_once_with(
            "high-frequency-batch-exports",
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


TEST_HOGQL_QUERY = """
SELECT
  event,
  team_id AS my_team,
  properties,
  properties.$browser AS browser,
  properties.custom AS custom,
  person_id
FROM events
"""


def test_create_batch_export_with_custom_schema(
    client: HttpClient, temporal, encryption_codec, organization, team, user
):
    """Test creating a BatchExport with a custom schema expressed as a HogQL Query.

    When creating a BatchExport, we should create a corresponding Schedule in
    Temporal as described by the associated BatchExportSchedule model. In this
    test we assert this Schedule is created in Temporal and populated with the
    expected inputs.
    """

    destination_data = {
        "type": "AwsS3",
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
        "hogql_query": TEST_HOGQL_QUERY,
        "interval": "hour",
    }

    client.force_login(user)

    response = create_batch_export(
        client,
        team.pk,
        batch_export_data,
    )

    assert response.status_code == status.HTTP_201_CREATED, response.json()

    data = response.json()
    expected_hogql_query = " ".join(TEST_HOGQL_QUERY.split())  # Don't care about whitespace
    assert data["schema"]["hogql_query"] == expected_hogql_query

    schedule = describe_schedule(temporal, data["id"])

    batch_export = BatchExport.objects.get(id=data["id"])

    decoded_payload = async_to_sync(encryption_codec.decode)(schedule.schedule.action.args)
    args = json.loads(decoded_payload[0].data)

    expected_fields = [
        {"expression": "events.event", "alias": "event"},
        {"expression": "events.team_id", "alias": "my_team"},
        {"expression": "events.properties", "alias": "properties"},
        {
            "expression": "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', '')",
            "alias": "browser",
        },
        {
            "expression": "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', '')",
            "alias": "custom",
        },
        {"alias": "person_id", "expression": "events.person_id"},
    ]
    expected_schema = {
        "fields": expected_fields,
        "values": {
            "hogql_val_0": "$browser",
            "hogql_val_1": "custom",
        },
        "hogql_query": expected_hogql_query,
    }

    assert batch_export.schema == expected_schema
    assert args["batch_export_model"] == {"filters": None, "name": "events", "schema": expected_schema}


@pytest.mark.parametrize(
    "invalid_query,expected_error_message",
    [
        ("SELECT", "Failed to parse query"),
        ("SELECT event,, FROM events", "Failed to parse query"),
        ("SELECT unknown_field FROM events", "Invalid HogQL query: Unable to resolve field: unknown_field"),
        (
            "SELECT event, persons.id FROM events LEFT JOIN persons ON events.person_id = persons.id",
            "JOINs are not supported",
        ),
        ("SELECT event FROM events UNION ALL SELECT event FROM events", "UNIONs are not supported"),
        ("WITH cte AS (SELECT event FROM events) SELECT event FROM cte", "CTEs are not supported"),
        ("SELECT event FROM (SELECT event FROM events)", "Subqueries are not supported"),
        (
            "SELECT event FROM (SELECT event FROM events UNION ALL SELECT event FROM events)",
            "Subqueries are not supported",
        ),
        (
            "SELECT uuid, (SELECT event FROM events LIMIT 1) AS leaked FROM events",
            "Subqueries in SELECT expressions are not supported",
        ),
        (
            "SELECT coalesce((SELECT uuid FROM events LIMIT 1), uuid) AS foo FROM events",
            "Subqueries in SELECT expressions are not supported",
        ),
    ],
)
def test_create_batch_export_fails_with_invalid_query(
    client: HttpClient, invalid_query, expected_error_message, temporal, organization, team, user
):
    """Test creating a BatchExport should fail with an invalid query."""

    destination_data = {
        "type": "AwsS3",
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
        "hogql_query": invalid_query,
    }

    client.force_login(user)

    response = create_batch_export(
        client,
        team.pk,
        batch_export_data,
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert response.json()["detail"] == expected_error_message


@pytest.mark.parametrize(
    "type,config,expected_error_message",
    [
        (
            "Snowflake",
            {
                "account": "my-account",
                "user": "user",
                "database": "my-db",
                "warehouse": "COMPUTE_WH",
                "schema": "public",
                "table_name": 2,  # Wrong type
                "authentication_type": "keypair",
                "private_key": "SECRET_KEY",
            },
            "invalid type: got 'int', expected 'str'",
        ),
        (
            "AwsS3",
            {
                "bucket_name": "my-s3-bucket",
                "region": "us-east-1",
                "prefix": "posthog-events/",
                "aws_access_key_id": "abc123",
                "aws_secret_access_key": "secret",
                "hello": 123,  # Unknown field
                "hello2": 123,  # Another unknown field
            },
            "unknown field/s: 'hello', 'hello2'",
        ),
        (
            "Postgres",
            {
                "user": "test",
                "password": "password",
                "host": "localhost",
                "database": "db",
                "schema": None,  # Not optional
                "table_name": "test",
            },
            "invalid type: got 'NoneType', expected 'str'",
        ),
        (
            "BigQuery",
            {
                "project_id": "test",
                # Missing required `dataset_id`
                "private_key": "pkey",
                "private_key_id": "pkey_id",
                "token_uri": "token",
                "client_email": "email",
            },
            "missing required field: 'dataset_id'",
        ),
    ],
)
def test_create_batch_export_with_invalid_config(
    client: HttpClient, temporal, type, config, expected_error_message, organization, team, user
):
    """Test creating a BatchExport with an invalid configuration returns an error."""

    destination_data = {
        "type": type,
        "config": config,
    }

    batch_export_data = {
        "name": "destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)

    response = create_batch_export(
        client,
        team.pk,
        batch_export_data,
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert expected_error_message in response.json()["detail"]


_S3_FILTER_TEST_CONFIG = {
    "bucket_name": "my-s3-bucket",
    "region": "us-east-1",
    "prefix": "posthog-events/",
    "aws_access_key_id": "abc123",
    "aws_secret_access_key": "secret",
}


@pytest.mark.parametrize(
    "filters,expected_status,expected_error",
    [
        ({"filters": {"filter_something": 123}}, status.HTTP_400_BAD_REQUEST, "should be an array"),
        (None, status.HTTP_201_CREATED, None),
        ([], status.HTTP_201_CREATED, None),
        (
            [{"data_interval_start": "2025-01-01"}],
            status.HTTP_400_BAD_REQUEST,
            "not 'filters'. Trigger a backfill",
        ),
    ],
)
def test_creating_batch_export_with_filters(
    client: HttpClient,
    temporal,
    organization,
    team,
    user,
    filters,
    expected_status,
    expected_error,
):
    """Test validation of the filters field when creating a batch export."""

    destination_data = {
        "type": "AwsS3",
        "config": _S3_FILTER_TEST_CONFIG,
    }

    batch_export_data = {
        "name": "my-destination",
        "destination": destination_data,
        "interval": "hour",
        "model": "events",
        "filters": filters,
    }

    client.force_login(user)
    response = create_batch_export(
        client,
        team.pk,
        batch_export_data,
    )

    assert response.status_code == expected_status, response.json()

    if expected_error:
        assert expected_error in response.json()["detail"]


@pytest.mark.parametrize(
    "host",
    [
        "192.168.1.1",
        "127.0.0.1",
        "[::1]",
        "10.0.0.1",
        "169.254.0.0",
        "localhost",
    ],
)
def test_create_redshift_batch_export_fails_with_invalid_host(
    client: HttpClient, temporal, organization, team, user, host
):
    """Test creating a BatchExport with Redshift destination validates inputs for 'COPY'.

    Postgres host validation is covered separately in test_create_postgres.py, where the host
    comes from the linked Integration rather than from inline config.
    """

    destination_data = {
        "type": "Redshift",
        "config": {
            "user": "user",
            "password": "my-password",
            "database": "my-db",
            "host": host,
            "schema": "public",
            "table_name": "my_events",
        },
    }

    batch_export_data = {
        "name": "my-production-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)

    with override_settings(TEST=0, DEBUG=0):
        response = create_batch_export(
            client,
            team.pk,
            batch_export_data,
        )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert f"Invalid host: '{host}'" in response.json()["detail"]
