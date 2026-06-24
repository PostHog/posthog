import json
import typing as t
import datetime as dt

import pytest

from django.test.client import Client as HttpClient

from asgiref.sync import async_to_sync
from rest_framework import status

from posthog.models.integration import Integration

from products.batch_exports.backend.models.batch_export import BatchExport, BatchExportDestination
from products.batch_exports.backend.service import sync_batch_export
from products.batch_exports.backend.tests.api.conftest import (
    assert_is_daily_schedule,
    assert_is_weekly_schedule,
    describe_schedule,
)
from products.batch_exports.backend.tests.api.operations import (
    create_batch_export_ok,
    get_batch_export_ok,
    patch_batch_export,
    put_batch_export,
)

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("temporal_worker", "cleanup"),
]


@pytest.fixture
def bigquery_integration(team, user):
    """Create a Google Cloud Service Account integration for BigQuery."""
    return Integration.objects.create(
        team=team,
        kind=Integration.IntegrationKind.GOOGLE_CLOUD_SERVICE_ACCOUNT,
        integration_id="test-bigquery-service-account",
        config={"project_id": "test", "service_account_email": "email"},
        sensitive_config={
            "private_key": "pkey",
            "private_key_id": "pkey_id",
            "token_uri": "token",
        },
        created_by=user,
    )


def test_can_put_config(client: HttpClient, temporal, encryption_codec, organization, team, user):
    destination_data: dict[str, t.Any] = {
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
    new_schedule = describe_schedule(temporal, batch_export["id"])
    assert_is_daily_schedule(new_schedule, 0)
    assert new_schedule.schedule.spec.start_at == dt.datetime(2022, 7, 19, 0, 0, 0, tzinfo=dt.UTC)
    assert new_schedule.schedule.spec.end_at == dt.datetime(2023, 7, 20, 0, 0, 0, tzinfo=dt.UTC)
    assert new_schedule.schedule.spec.time_zone_name == "UTC"  # UTC is the default timezone if not provided

    decoded_payload = async_to_sync(encryption_codec.decode)(new_schedule.schedule.action.args)
    args = json.loads(decoded_payload[0].data)
    assert args["bucket_name"] == "my-new-production-s3-bucket"
    assert args["aws_secret_access_key"] == "new-secret"


@pytest.mark.parametrize("interval", ["hour", "day"])
def test_can_patch_config(client: HttpClient, interval, temporal, encryption_codec, organization, team, user):
    timezone = "Europe/Berlin"
    # use offset of 1 hour for daily exports and None for hourly exports (these don't support offsets)
    offset_hour = None if interval == "hour" else 1
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
        "type": "AwsS3",
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
    new_schedule = describe_schedule(temporal, batch_export["id"])
    if interval == "day":
        expected_hour = offset_hour if offset_hour is not None else 0
        assert_is_daily_schedule(old_schedule, expected_hour)
        assert_is_daily_schedule(new_schedule, expected_hour)
    else:
        assert new_schedule.schedule.spec.intervals[0].every == dt.timedelta(hours=1)
        assert old_schedule.schedule.spec.intervals[0].every == new_schedule.schedule.spec.intervals[0].every
    decoded_payload = async_to_sync(encryption_codec.decode)(new_schedule.schedule.action.args)
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
def test_can_patch_config_with_invalid_old_values(
    client: HttpClient, encryption_codec, interval, temporal, organization, team, user
):
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
    new_schedule = describe_schedule(temporal, batch_export_data["id"])
    decoded_payload = async_to_sync(encryption_codec.decode)(new_schedule.schedule.action.args)
    args = json.loads(decoded_payload[0].data)
    assert args["bucket_name"] == "my-new-production-s3-bucket"
    assert args.get("invalid_key", None) is None


def test_patch_rejects_destination_type_change(
    client: HttpClient,
    temporal,
    organization,
    team,
    user,
    bigquery_integration,
):
    """Assert PATCH cannot change the destination type — callers must delete and recreate."""
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

    client.force_login(user)
    batch_export = create_batch_export_ok(client, team.pk, batch_export_data)

    new_destination_data = {
        "type": "BigQuery",
        "integration_id": bigquery_integration.id,
        "config": {
            "table_id": "test",
            "dataset_id": "test",
        },
    }
    response = patch_batch_export(
        client,
        team.pk,
        batch_export["id"],
        {"destination": new_destination_data},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Cannot change destination type" in response.json()["detail"]

    # The original destination is still intact.
    refreshed = get_batch_export_ok(client, team.pk, batch_export["id"])
    assert refreshed["destination"]["type"] == "AwsS3"
    assert refreshed["destination"]["config"]["bucket_name"] == "my-production-s3-bucket"


def test_put_rejects_destination_type_change(
    client: HttpClient,
    temporal,
    organization,
    team,
    user,
):
    """Assert PUT cannot change the destination type either — same restriction as PATCH."""
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

    client.force_login(user)
    batch_export = create_batch_export_ok(client, team.pk, batch_export_data)

    new_batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": {
            "type": "BigQuery",
            "config": {
                "table_id": "test",
                "dataset_id": "test",
                "project_id": "test",
            },
        },
        "interval": "hour",
    }
    response = put_batch_export(client, team.pk, batch_export["id"], new_batch_export_data)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Cannot change destination type" in response.json()["detail"]

    # The original destination is still intact.
    refreshed = get_batch_export_ok(client, team.pk, batch_export["id"])
    assert refreshed["destination"]["type"] == "AwsS3"
    assert refreshed["destination"]["config"]["bucket_name"] == "my-production-s3-bucket"


def test_can_patch_hogql_query(client: HttpClient, temporal, encryption_codec, organization, team, user):
    """Test we can patch a schema with a HogQL query."""
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
    new_schedule = describe_schedule(temporal, batch_export["id"])
    assert old_schedule.schedule.spec.intervals[0].every == new_schedule.schedule.spec.intervals[0].every
    decoded_payload = async_to_sync(encryption_codec.decode)(new_schedule.schedule.action.args)
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


def test_can_update_batch_export_with_integration(
    client: HttpClient,
    temporal,
    encryption_codec,
    organization,
    team,
    user,
    databricks_integration,
    databricks_integration_2,
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
    new_schedule = describe_schedule(temporal, batch_export["id"])
    assert old_schedule.schedule.spec.intervals[0].every == new_schedule.schedule.spec.intervals[0].every
    decoded_payload = async_to_sync(encryption_codec.decode)(new_schedule.schedule.action.args)
    args = json.loads(decoded_payload[0].data)
    assert args["integration_id"] == databricks_integration_2.id


def test_can_update_batch_export_with_integration_to_none(
    client: HttpClient,
    temporal,
    organization,
    team,
    user,
    databricks_integration,
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


def test_updating_legacy_postgres_batch_export_keeps_inline_credentials(
    client: HttpClient, temporal, organization, team, user
):
    """Test that existing inline-credential Postgres exports are grandfathered when edited.

    Exports created before integrations existed have no linked integration. Editing them must
    not force migrating to an integration, so the integration requirement applies on create only.
    """
    destination = BatchExportDestination.objects.create(
        type=BatchExportDestination.Destination.POSTGRES,
        config={
            "user": "user",
            "password": "my-password",
            "host": "8.8.8.8",
            "port": 5432,
            "database": "my-db",
            "schema": "public",
            "table_name": "my_events",
        },
    )
    batch_export = BatchExport.objects.create(
        name="legacy-postgres-export", team=team, destination=destination, interval="hour"
    )
    sync_batch_export(batch_export, created=True)

    client.force_login(user)
    new_batch_export_data = {
        "destination": {
            "type": "Postgres",
            "config": {"table_name": "my_new_events"},
        },
    }
    response = patch_batch_export(client, team.pk, batch_export.id, new_batch_export_data)

    assert response.status_code == status.HTTP_200_OK, response.json()
    updated = get_batch_export_ok(client, team.pk, batch_export.id)
    assert updated["destination"]["config"]["table_name"] == "my_new_events"
