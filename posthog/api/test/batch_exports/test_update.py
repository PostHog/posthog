import json
import typing as t
import datetime as dt

import pytest
from unittest import mock

from django.conf import settings
from django.test.client import Client as HttpClient

from asgiref.sync import async_to_sync
from rest_framework import status

from posthog.api.test.batch_exports.conftest import (
    assert_is_daily_schedule,
    assert_is_weekly_schedule,
    describe_schedule,
)
from posthog.api.test.batch_exports.operations import (
    create_batch_export_ok,
    get_batch_export_ok,
    patch_batch_export,
    put_batch_export,
)
from posthog.batch_exports.service import sync_batch_export
from posthog.models import BatchExport, BatchExportDestination
from posthog.models.integration import Integration
from posthog.temporal.common.codec import EncryptionCodec

pytestmark = [
    pytest.mark.django_db,
]


def test_can_put_config(client: HttpClient, temporal, organization, team, user):
    destination_data: dict[str, t.Any] = {
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
        "start_at": "2023-07-19T00:00:00+00:00",
        "end_at": "2023-07-20T00:00:00+00:00",
    }

    client.force_login(user)

    batch_export = create_batch_export_ok(
        client,
        team.pk,
        batch_export_data,
    )

    # If we try to update without all fields, it should fail with a 400 error
    new_batch_export_data: dict[str, t.Any] = {
        "name": "my-production-s3-bucket-destination",
        "interval": "hour",
    }
    response = put_batch_export(client, team.pk, batch_export["id"], new_batch_export_data)
    assert response.status_code == status.HTTP_400_BAD_REQUEST

    old_schedule = describe_schedule(temporal, batch_export["id"])
    assert old_schedule.schedule.spec.intervals[0].every == dt.timedelta(hours=1)

    # We should be able to update if we specify all fields
    new_destination_data = {**destination_data}
    new_destination_data["config"]["bucket_name"] = "my-new-production-s3-bucket"
    new_destination_data["config"]["aws_secret_access_key"] = "new-secret"
    new_batch_export_data_2: dict[str, t.Any] = {
        "name": "my-production-s3-bucket-destination",
        "destination": new_destination_data,
        "interval": "day",
        "start_at": "2022-07-19 00:00:00",
    }

    response = put_batch_export(client, team.pk, batch_export["id"], new_batch_export_data_2)
    assert response.status_code == status.HTTP_200_OK

    # get the batch export and validate e.g. that interval has been updated to day
    batch_export = get_batch_export_ok(client, team.pk, batch_export["id"])
    assert batch_export["interval"] == "day"
    assert batch_export["timezone"] == "UTC"
    assert batch_export["offset_day"] is None
    assert batch_export["offset_hour"] == 0

    # validate the underlying temporal schedule has been updated
    codec = EncryptionCodec(settings=settings)
    new_schedule = describe_schedule(temporal, batch_export["id"])
    assert_is_daily_schedule(new_schedule, 0)
    assert new_schedule.schedule.spec.start_at == dt.datetime(2022, 7, 19, 0, 0, 0, tzinfo=dt.UTC)
    assert new_schedule.schedule.spec.end_at == dt.datetime(2023, 7, 20, 0, 0, 0, tzinfo=dt.UTC)
    assert new_schedule.schedule.spec.time_zone_name == "UTC"  # UTC is the default timezone if not provided

    decoded_payload = async_to_sync(codec.decode)(new_schedule.schedule.action.args)
    args = json.loads(decoded_payload[0].data)
    assert args["bucket_name"] == "my-new-production-s3-bucket"
    assert args["aws_secret_access_key"] == "new-secret"


@pytest.mark.parametrize("interval", ["hour", "day"])
def test_can_patch_config(client: HttpClient, interval, temporal, organization, team, user):
    timezone = "Europe/Berlin"
    # use offset of 1 hour for daily exports and None for hourly exports (these don't support offsets)
    offset_hour = None if interval == "hour" else 1
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
    }
    if offset_hour is not None:
        batch_export_data["offset_hour"] = offset_hour

    # create a team with a timezone different to the one we are testing to ensure this has no effect on the batch export
    team.timezone = "Asia/Seoul"
    team.save()

    client.force_login(user)

    batch_export = create_batch_export_ok(
        client,
        team.pk,
        batch_export_data,
    )
    old_schedule = describe_schedule(temporal, batch_export["id"])

    # We should be able to update the destination config, excluding the aws
    # credentials. The existing values should be preserved.
    new_destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": "my-new-production-s3-bucket",
            "region": "us-east-1",
            "prefix": "posthog-events/",
        },
    }

    new_batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": new_destination_data,
    }

    response = patch_batch_export(client, team.pk, batch_export["id"], new_batch_export_data)
    assert response.status_code == status.HTTP_200_OK, response.json()

    # get the batch export and validate e.g. that bucket_name and interval
    # has been preserved.
    batch_export_data = get_batch_export_ok(client, team.pk, batch_export["id"])
    assert batch_export_data["interval"] == interval
    assert batch_export_data["timezone"] == timezone
    if interval == "day":
        assert batch_export_data["offset_hour"] == offset_hour
        assert batch_export_data["offset_day"] is None
    else:
        assert batch_export_data["offset_hour"] is None
        assert batch_export_data["offset_day"] is None
    assert batch_export_data["destination"]["config"]["bucket_name"] == "my-new-production-s3-bucket"

    # validate the underlying temporal schedule has been updated
    codec = EncryptionCodec(settings=settings)
    new_schedule = describe_schedule(temporal, batch_export["id"])
    if interval == "day":
        expected_hour = offset_hour if offset_hour is not None else 0
        assert_is_daily_schedule(old_schedule, expected_hour)
        assert_is_daily_schedule(new_schedule, expected_hour)
    else:
        assert new_schedule.schedule.spec.intervals[0].every == dt.timedelta(hours=1)
        assert old_schedule.schedule.spec.intervals[0].every == new_schedule.schedule.spec.intervals[0].every
    decoded_payload = async_to_sync(codec.decode)(new_schedule.schedule.action.args)
    args = json.loads(decoded_payload[0].data)
    assert args["bucket_name"] == "my-new-production-s3-bucket"
    assert new_schedule.schedule.spec.time_zone_name == timezone


@pytest.mark.parametrize(
    "initial_state,patch_data,expected_state,expected_error",
    [
        pytest.param(
            {
                "interval": "hour",
                "timezone": "UTC",
                "offset_day": None,
                "offset_hour": None,
            },
            {
                "interval": "week",
                "timezone": "UTC",
                "offset_day": 0,
                "offset_hour": 0,
            },
            {
                "interval": "week",
                "timezone": "UTC",
                "offset_day": 0,
                "offset_hour": 0,
                "interval_offset": 0,
            },
            None,
            id="Changing from hourly to weekly",
        ),
        pytest.param(
            {
                "interval": "hour",
                "timezone": None,
                "offset_day": None,
                "offset_hour": None,
            },
            {
                "interval": "week",
            },
            {
                "interval": "week",
                "timezone": "UTC",  # should default to UTC if not provided
                "offset_day": 0,
                "offset_hour": 0,
                "interval_offset": None,  # should default to None if not provided
            },
            None,
            id="Changing from hourly to weekly (timezone and offset are not provided in update)",
        ),
        pytest.param(
            {
                "interval": "day",
                "timezone": "Europe/Berlin",
                "offset_day": None,
                "offset_hour": 1,
            },
            {
                "interval": "hour",
            },
            {
                "interval": "hour",
                "timezone": "Europe/Berlin",  # timezone should be preserved
                "offset_day": None,  # should be reset to None as hourly exports don't support offsets
                "offset_hour": None,  # should be reset to None as hourly exports don't support offsets
                "interval_offset": None,  # should be reset to None as hourly exports don't support offsets
            },
            None,
            id="Changing from daily to hourly (timezone and offset are not provided in update)",
        ),
        pytest.param(
            {
                "interval": "day",
                "timezone": "Europe/Berlin",
                "offset_day": None,
                "offset_hour": 1,
            },
            {
                "interval": "day",
                "timezone": None,
                "offset_day": None,
                "offset_hour": None,
            },
            {
                "interval": "day",
                "timezone": "UTC",  # if None is provided, we should default to UTC
                "offset_day": None,  # if None is provided, we should reset the offset to None
                "offset_hour": 0,  # if None is provided, we should reset the offset to 0
                "interval_offset": None,  # if None is provided, we should reset the offset to None
            },
            None,
            id="Resetting timezone and offset to default values",
        ),
        pytest.param(
            {
                "interval": "day",
                "timezone": "Europe/Berlin",
                "offset_day": None,
                "offset_hour": 1,
            },
            {
                "interval": None,
                "timezone": None,
                "offset_day": None,
                "offset_hour": None,
            },
            None,
            "This field may not be null.",
            id="Interval is None in update data",
        ),
        pytest.param(
            {
                "interval": "hour",
                "timezone": None,
                "offset_day": None,
                "offset_hour": None,
            },
            {
                "interval": "day",
                "timezone": "US/Pacific",
                "offset_hour": 2,
            },
            {
                "interval": "day",
                "timezone": "US/Pacific",
                "offset_day": None,
                "offset_hour": 2,
                "interval_offset": 7200,  # 2 hours = 7200 seconds
            },
            None,
            id="Changing from hourly to daily and updating timezone and offset",
        ),
        pytest.param(
            {
                "interval": "hour",
                "timezone": "UTC",
                "offset_day": None,
                "offset_hour": None,
            },
            {
                "interval": "day",
                "timezone": "US/Pacific",
                "offset_hour": 24,
            },
            None,
            "Ensure this value is less than or equal to 23.",
            id="24 hour offset is invalid for a daily export",
        ),
        pytest.param(
            {
                "interval": "day",
                "timezone": "US/Pacific",
                "offset_day": None,
                "offset_hour": None,
            },
            {
                "interval": "week",
                "timezone": "UTC",
                "offset_day": 7,
                "offset_hour": 0,
            },
            None,
            "Ensure this value is less than or equal to 6.",
            id="7 day offset is invalid for a weekly export",
        ),
        pytest.param(
            {
                "interval": "week",
                "timezone": "UTC",
                "offset_day": None,
                "offset_hour": None,
            },
            {"interval": "hour", "timezone": "Europe/Berlin", "offset_hour": 1},
            None,
            "offset_hour is not applicable for non-daily/weekly intervals",
        ),
    ],
)
def test_can_patch_schedule_configuration(
    client: HttpClient,
    temporal,
    organization,
    team,
    user,
    initial_state,
    patch_data,
    expected_state,
    expected_error,
):
    """Test patching schedule configuration (interval, timezone, offset) updates the schedule spec correctly.

    NOTE: When patching the configuration, there is a difference between including a field with a None value and not
    including it at all. If provided, we should use the provided value (or set it to the default if None). If not
    provided, we should keep the existing value.
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
        "interval": initial_state["interval"],
        "timezone": initial_state["timezone"],
    }
    if "offset_day" in initial_state:
        batch_export_data["offset_day"] = initial_state["offset_day"]
    if "offset_hour" in initial_state:
        batch_export_data["offset_hour"] = initial_state["offset_hour"]

    client.force_login(user)

    batch_export = create_batch_export_ok(
        client,
        team.pk,
        batch_export_data,
    )

    new_batch_export_data = {}
    if "interval" in patch_data:
        new_batch_export_data["interval"] = patch_data["interval"]
    if "timezone" in patch_data:
        new_batch_export_data["timezone"] = patch_data["timezone"]
    if "offset_day" in patch_data:
        new_batch_export_data["offset_day"] = patch_data["offset_day"]
    if "offset_hour" in patch_data:
        new_batch_export_data["offset_hour"] = patch_data["offset_hour"]

    response = patch_batch_export(client, team.pk, batch_export["id"], new_batch_export_data)
    if expected_error:
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert expected_error in response.json()["detail"]
        return
    assert response.status_code == status.HTTP_200_OK, response.json()

    batch_export = get_batch_export_ok(client, team.pk, batch_export["id"])
    assert batch_export["interval"] == expected_state["interval"]
    assert batch_export["timezone"] == expected_state["timezone"]
    assert batch_export["offset_day"] == expected_state["offset_day"]
    assert batch_export["offset_hour"] == expected_state["offset_hour"]

    new_schedule = describe_schedule(temporal, batch_export["id"])
    batch_export_model = BatchExport.objects.get(id=batch_export["id"])

    # Verify interval_offset in the database matches expected value
    assert batch_export_model.interval_offset == expected_state["interval_offset"]

    assert new_schedule.schedule.spec.time_zone_name == expected_state["timezone"]

    # Verify the schedule spec matches the new interval type
    if expected_state["interval"] == "day":
        # Daily exports use ScheduleCalendarSpec
        expected_hour = expected_state["offset_hour"] if expected_state["offset_hour"] is not None else 0
        assert_is_daily_schedule(new_schedule, expected_hour)
    elif expected_state["interval"] == "week":
        # Weekly exports use ScheduleCalendarSpec
        day_offset = expected_state["offset_day"] if expected_state["offset_day"] is not None else 0
        hour_offset = expected_state["offset_hour"] if expected_state["offset_hour"] is not None else 0
        assert_is_weekly_schedule(new_schedule, day_offset, hour_offset)
    else:
        # Other intervals use ScheduleIntervalSpec
        assert len(new_schedule.schedule.spec.intervals) == 1
        assert new_schedule.schedule.spec.intervals[0].every == batch_export_model.interval_time_delta


@pytest.mark.django_db
@pytest.mark.parametrize("interval", ["hour", "day"])
def test_can_patch_config_with_invalid_old_values(client: HttpClient, interval, temporal, organization, team, user):
    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": "my-production-s3-bucket",
            "region": "us-east-1",
            "prefix": "posthog-events/",
            "aws_access_key_id": "abc123",
            "aws_secret_access_key": "secret",
            "invalid_key": "invalid_value",
        },
    }

    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "interval": interval,
    }

    client.force_login(user)

    # Create a BatchExport straight in the database/temporal to avoid going through the API
    # as that's what we are trying to test here.
    destination = BatchExportDestination(**destination_data)
    batch_export = BatchExport(team=team, destination=destination, **batch_export_data)

    sync_batch_export(batch_export, created=True)

    destination.save()
    batch_export.save()

    # We should be able to update the destination config, even if there is an invalid config
    # in the existing keys.
    new_destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": "my-new-production-s3-bucket",
            "region": "us-east-1",
            "prefix": "posthog-events/",
        },
    }

    new_batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": new_destination_data,
    }

    response = patch_batch_export(client, team.pk, batch_export.id, new_batch_export_data)
    assert response.status_code == status.HTTP_200_OK, response.json()

    # get the batch export and validate e.g. that bucket_name and interval
    # has been preserved.
    batch_export_data = get_batch_export_ok(client, team.pk, batch_export.id)
    assert batch_export_data["interval"] == interval
    assert batch_export_data["destination"]["config"]["bucket_name"] == "my-new-production-s3-bucket"

    # validate the underlying temporal schedule has been updated
    codec = EncryptionCodec(settings=settings)
    new_schedule = describe_schedule(temporal, batch_export_data["id"])
    decoded_payload = async_to_sync(codec.decode)(new_schedule.schedule.action.args)
    args = json.loads(decoded_payload[0].data)
    assert args["bucket_name"] == "my-new-production-s3-bucket"
    assert args.get("invalid_key", None) is None


def test_can_patch_hogql_query(client: HttpClient, temporal, organization, team, user):
    """Test we can patch a schema with a HogQL query."""
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

    batch_export = create_batch_export_ok(
        client,
        team.pk,
        batch_export_data,
    )
    old_schedule = describe_schedule(temporal, batch_export["id"])

    new_batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "hogql_query": "select toString(uuid) as uuid, 'test' as test, toInt(1+1) as n from events",
    }

    response = patch_batch_export(client, team.pk, batch_export["id"], new_batch_export_data)
    assert response.status_code == status.HTTP_200_OK, response.json()

    response_data: dict[str, t.Any] = get_batch_export_ok(client, team.pk, batch_export["id"])
    assert response_data["interval"] == "hour"
    assert response_data["destination"]["config"]["bucket_name"] == "my-production-s3-bucket"
    assert response_data["schema"] == {
        "fields": [
            {
                "alias": "uuid",
                "expression": "toString(events.uuid)",
            },
            {
                "alias": "test",
                "expression": "%(hogql_val_0)s",
            },
            {
                "alias": "n",
                "expression": "accurateCastOrNull(plus(1, 1), %(hogql_val_1)s)",
            },
        ],
        "values": {"hogql_val_0": "test", "hogql_val_1": "Int64"},
        "hogql_query": "SELECT toString(uuid) AS uuid, 'test' AS test, toInt(plus(1, 1)) AS n FROM events",
    }

    # validate the underlying temporal schedule has been updated
    codec = EncryptionCodec(settings=settings)
    new_schedule = describe_schedule(temporal, batch_export["id"])
    assert old_schedule.schedule.spec.intervals[0].every == new_schedule.schedule.spec.intervals[0].every
    decoded_payload = async_to_sync(codec.decode)(new_schedule.schedule.action.args)
    args = json.loads(decoded_payload[0].data)
    assert args["bucket_name"] == "my-production-s3-bucket"
    assert args["interval"] == "hour"
    assert args["batch_export_model"] == {
        "name": "events",
        "filters": None,
        "schema": {
            "fields": [
                {
                    "alias": "uuid",
                    "expression": "toString(events.uuid)",
                },
                {
                    "alias": "test",
                    "expression": "%(hogql_val_0)s",
                },
                {
                    "alias": "n",
                    "expression": "accurateCastOrNull(plus(1, 1), %(hogql_val_1)s)",
                },
            ],
            "values": {"hogql_val_0": "test", "hogql_val_1": "Int64"},
            "hogql_query": "SELECT toString(uuid) AS uuid, 'test' AS test, toInt(plus(1, 1)) AS n FROM events",
        },
    }


def test_patch_returns_error_on_unsupported_hogql_query(client: HttpClient, temporal, organization, team, user):
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
        "start_at": "2023-07-19 00:00:00",
        "end_at": "2023-07-20 00:00:00",
    }

    client.force_login(user)

    batch_export = create_batch_export_ok(
        client,
        team.pk,
        batch_export_data,
    )

    new_batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        # toInt32 is not a supported HogQL function
        "hogql_query": "select toInt32(1+1) as n from events",
    }
    response = put_batch_export(client, team.pk, batch_export["id"], new_batch_export_data)
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_can_patch_snowflake_batch_export_credentials(client: HttpClient, temporal, organization, team, user):
    """Test we can switch Snowflake authentication types while preserving credentials."""
    destination_data = {
        "type": "Snowflake",
        "config": {
            "account": "my-account",
            "user": "user",
            "password": "password123",
            "database": "my-db",
            "warehouse": "COMPUTE_WH",
            "schema": "public",
            "table_name": "my_events",
            "authentication_type": "password",
        },
    }

    batch_export_data = {
        "name": "my-snowflake-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)

    batch_export = create_batch_export_ok(
        client,
        team.pk,
        batch_export_data,
    )

    # Test switching to key pair auth type
    new_destination_data = {
        "type": "Snowflake",
        "config": {
            "authentication_type": "keypair",
            "private_key": "SECRET_KEY",
        },
    }

    new_batch_export_data = {
        "destination": new_destination_data,
    }

    response = patch_batch_export(client, team.pk, batch_export["id"], new_batch_export_data)
    assert response.status_code == status.HTTP_200_OK, response.json()

    # Verify the auth type switch worked and other fields were preserved
    batch_export = get_batch_export_ok(client, team.pk, batch_export["id"])
    assert batch_export["destination"]["type"] == "Snowflake"
    assert batch_export["destination"]["config"]["account"] == "my-account"
    assert batch_export["destination"]["config"]["authentication_type"] == "keypair"
    assert "private_key" not in batch_export["destination"]["config"]  # Private key should be hidden in response

    # Test switching back to password auth type without providing password (should keep original)
    new_destination_data = {
        "type": "Snowflake",
        "config": {
            "authentication_type": "password",
        },
    }

    new_batch_export_data = {
        "destination": new_destination_data,
    }

    response = patch_batch_export(client, team.pk, batch_export["id"], new_batch_export_data)
    assert response.status_code == status.HTTP_200_OK, response.json()

    # Verify switched back to password auth and kept original password
    batch_export = get_batch_export_ok(client, team.pk, batch_export["id"])
    assert batch_export["destination"]["type"] == "Snowflake"
    assert batch_export["destination"]["config"]["account"] == "my-account"
    assert batch_export["destination"]["config"]["authentication_type"] == "password"
    assert "password" not in batch_export["destination"]["config"]  # Password should be hidden in response


def test_switching_snowflake_auth_type_to_keypair_requires_private_key(
    client: HttpClient, temporal, organization, team, user
):
    """Test that switching to keypair authentication requires a private key to be provided."""
    destination_data = {
        "type": "Snowflake",
        "config": {
            "account": "my-account",
            "user": "user",
            "password": "password123",
            "database": "my-db",
            "warehouse": "COMPUTE_WH",
            "schema": "public",
            "table_name": "my_events",
            "authentication_type": "password",
        },
    }

    batch_export_data = {
        "name": "my-snowflake-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)

    batch_export = create_batch_export_ok(
        client,
        team.pk,
        batch_export_data,
    )

    # Test switching to keypair auth type without providing a private key
    new_destination_data = {
        "type": "Snowflake",
        "config": {
            "authentication_type": "keypair",
        },
    }

    new_batch_export_data = {
        "destination": new_destination_data,
    }

    response = patch_batch_export(client, team.pk, batch_export["id"], new_batch_export_data)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Private key is required if authentication type is key pair" in response.json()["detail"]

    # Verify the auth type was not changed
    batch_export = get_batch_export_ok(client, team.pk, batch_export["id"])
    assert batch_export["destination"]["type"] == "Snowflake"
    assert batch_export["destination"]["config"]["authentication_type"] == "password"


@pytest.fixture
def databricks_integration(team, user):
    """Create a Databricks integration."""
    return Integration.objects.create(
        team=team,
        kind=Integration.IntegrationKind.DATABRICKS,
        integration_id="my-server-hostname",
        config={"server_hostname": "my-server-hostname"},
        sensitive_config={"client_id": "my-client-id", "client_secret": "my-client-secret"},
        created_by=user,
    )


@pytest.fixture
def databricks_integration_2(team, user):
    """Create a second Databricks integration."""
    return Integration.objects.create(
        team=team,
        kind=Integration.IntegrationKind.DATABRICKS,
        integration_id="my-server-hostname-2",
        config={"server_hostname": "my-server-hostname-2"},
        sensitive_config={"client_id": "my-client-id", "client_secret": "my-client-secret"},
        created_by=user,
    )


@pytest.fixture
def enable_databricks(team):
    """Enable the Databricks batch exports feature flag to be able to run the test."""
    with mock.patch(
        "posthog.batch_exports.http.posthoganalytics.feature_enabled",
        return_value=True,
    ):
        yield


def test_can_update_batch_export_with_integration(
    client: HttpClient,
    temporal,
    organization,
    team,
    user,
    databricks_integration,
    databricks_integration_2,
    enable_databricks,
):
    """Test we can update a batch export with an integration (for example Databricks)."""

    destination_data = {
        "type": "Databricks",
        "integration": databricks_integration.id,
        "config": {
            "http_path": "my-http-path",
            "catalog": "my-catalog",
            "schema": "my-schema",
            "table_name": "my-table-name",
        },
    }

    batch_export_data = {
        "name": "my-databricks-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)

    batch_export = create_batch_export_ok(
        client,
        team.pk,
        batch_export_data,
    )
    old_schedule = describe_schedule(temporal, batch_export["id"])

    new_batch_export_data = {
        "destination": {
            "type": "Databricks",
            "integration": databricks_integration_2.id,
            "config": {
                "http_path": "my-http-path",
                "catalog": "my-catalog",
                "schema": "my-schema",
                "table_name": "my-table-name",
            },
        },
    }

    response = patch_batch_export(client, team.pk, batch_export["id"], new_batch_export_data)
    assert response.status_code == status.HTTP_200_OK, response.json()

    response_data: dict[str, t.Any] = get_batch_export_ok(client, team.pk, batch_export["id"])
    assert response_data["interval"] == "hour"
    assert response_data["destination"]["integration"] == databricks_integration_2.id
    assert response_data["destination"]["config"] == {
        "http_path": "my-http-path",
        "catalog": "my-catalog",
        "schema": "my-schema",
        "table_name": "my-table-name",
    }

    # validate the underlying temporal schedule has been updated
    codec = EncryptionCodec(settings=settings)
    new_schedule = describe_schedule(temporal, batch_export["id"])
    assert old_schedule.schedule.spec.intervals[0].every == new_schedule.schedule.spec.intervals[0].every
    decoded_payload = async_to_sync(codec.decode)(new_schedule.schedule.action.args)
    args = json.loads(decoded_payload[0].data)
    assert args["integration_id"] == databricks_integration_2.id


def test_can_update_batch_export_with_integration_to_none(
    client: HttpClient,
    temporal,
    organization,
    team,
    user,
    databricks_integration,
    enable_databricks,
):
    """Test we cannot update a batch export that requires an integration to None."""

    destination_data = {
        "type": "Databricks",
        "integration": databricks_integration.id,
        "config": {
            "http_path": "my-http-path",
            "catalog": "my-catalog",
            "schema": "my-schema",
            "table_name": "my-table-name",
        },
    }

    batch_export_data = {
        "name": "my-databricks-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)

    batch_export = create_batch_export_ok(
        client,
        team.pk,
        batch_export_data,
    )

    new_batch_export_data = {
        "destination": {
            "type": "Databricks",
            "integration": None,
            "config": {
                "http_path": "my-http-path",
                "catalog": "my-catalog",
                "schema": "my-schema",
                "table_name": "my-table-name",
            },
        },
    }

    response = patch_batch_export(client, team.pk, batch_export["id"], new_batch_export_data)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Integration is required for Databricks batch exports" in response.json()["detail"]


def test_can_patch_redshift_batch_export(client: HttpClient, temporal, organization, team, user):
    """Test we can patch a Redshift batch export preserving credentials."""
    destination_data = {
        "type": "Redshift",
        "config": {
            "user": "user",
            "password": "my-password",
            "database": "my-db",
            "host": "test",
            "schema": "public",
            "table_name": "my_events",
            "mode": "COPY",
            "copy_inputs": {
                "s3_bucket": "my-production-s3-bucket",
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": {"aws_access_key_id": "abc123", "aws_secret_access_key": "secret"},
                "authorization": {"aws_access_key_id": "abc123", "aws_secret_access_key": "secret"},
            },
        },
    }

    batch_export_data = {
        "name": "my-production-redshiftn-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)

    batch_export = create_batch_export_ok(
        client,
        team.pk,
        batch_export_data,
    )

    # Updates bucket name, leaves everything else untouched.
    new_destination_data = {
        "type": "Redshift",
        "config": {
            "copy_inputs": {
                "s3_bucket": "my-new-production-s3-bucket",
            },
        },
    }

    new_batch_export_data = {
        "destination": new_destination_data,
    }

    response = patch_batch_export(client, team.pk, batch_export["id"], new_batch_export_data)
    assert response.status_code == status.HTTP_200_OK, response.json()

    # Verify the bucket name update worked
    batch_export = get_batch_export_ok(client, team.pk, batch_export["id"])
    assert batch_export["destination"]["type"] == "Redshift"
    assert batch_export["destination"]["config"]["copy_inputs"]["s3_bucket"] == "my-new-production-s3-bucket"


def test_updating_s3_batch_export_validates_missing_inputs(client: HttpClient, temporal, organization, team, user):
    """Test updating a BatchExport with S3 destination validates that expected inputs are not empty."""

    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": "my-s3-bucket",
            "region": "us-east-1",
            "prefix": "events/",
            "aws_access_key_id": "abc123",
            "aws_secret_access_key": "secret",
            "file_format": "JSONLines",
            "compression": "gzip",
        },
    }

    batch_export_data = {
        "name": "my-s3-bucket",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)

    batch_export = create_batch_export_ok(client, team.pk, batch_export_data)

    response = patch_batch_export(
        client,
        team.pk,
        batch_export["id"],
        {
            "destination": {
                "type": "S3",
                "config": {
                    "bucket_name": "my-new-bucket",
                    "aws_access_key_id": "",
                    "aws_secret_access_key": "",
                },
            },
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["detail"] == "The following inputs are empty: ['aws_access_key_id', 'aws_secret_access_key']"
