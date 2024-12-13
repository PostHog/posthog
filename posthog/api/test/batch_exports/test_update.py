import datetime as dt
import json

import pytest
from asgiref.sync import async_to_sync
from django.conf import settings
from django.test.client import Client as HttpClient
from rest_framework import status

from posthog.api.test.batch_exports.conftest import describe_schedule, start_test_worker
from posthog.api.test.batch_exports.operations import (
    create_batch_export_ok,
    get_batch_export_ok,
    patch_batch_export,
    put_batch_export,
)
from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.batch_exports.service import sync_batch_export
from posthog.models import BatchExport, BatchExportDestination
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.codec import EncryptionCodec

pytestmark = [
    pytest.mark.django_db,
]


def test_can_put_config(client: HttpClient):
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
        "start_at": "2023-07-19T00:00:00+00:00",
        "end_at": "2023-07-20T00:00:00+00:00",
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

        # If we try to update without all fields, it should fail with a 400 error
        new_batch_export_data = {
            "name": "my-production-s3-bucket-destination",
            "interval": "hour",
        }
        response = put_batch_export(client, team.pk, batch_export["id"], new_batch_export_data)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        old_schedule = describe_schedule(temporal, batch_export["id"])

        # We should be able to update if we specify all fields
        new_destination_data = {**destination_data}
        new_destination_data["config"]["bucket_name"] = "my-new-production-s3-bucket"
        new_destination_data["config"]["aws_secret_access_key"] = "new-secret"
        new_batch_export_data = {
            "name": "my-production-s3-bucket-destination",
            "destination": new_destination_data,
            "interval": "day",
            "start_at": "2022-07-19 00:00:00",
        }

        response = put_batch_export(client, team.pk, batch_export["id"], new_batch_export_data)
        assert response.status_code == status.HTTP_200_OK

        # get the batch export and validate e.g. that interval has been updated to day
        batch_export = get_batch_export_ok(client, team.pk, batch_export["id"])
        assert batch_export["interval"] == "day"

        # validate the underlying temporal schedule has been updated
        codec = EncryptionCodec(settings=settings)
        new_schedule = describe_schedule(temporal, batch_export["id"])
        assert old_schedule.schedule.spec.intervals[0].every != new_schedule.schedule.spec.intervals[0].every
        assert new_schedule.schedule.spec.intervals[0].every == dt.timedelta(days=1)
        assert new_schedule.schedule.spec.start_at == dt.datetime(2022, 7, 19, 0, 0, 0, tzinfo=dt.UTC)
        assert new_schedule.schedule.spec.end_at == dt.datetime(2023, 7, 20, 0, 0, 0, tzinfo=dt.UTC)

        decoded_payload = async_to_sync(codec.decode)(new_schedule.schedule.action.args)
        args = json.loads(decoded_payload[0].data)
        assert args["bucket_name"] == "my-new-production-s3-bucket"
        assert args["aws_secret_access_key"] == "new-secret"


@pytest.mark.parametrize("interval", ["hour", "day"])
@pytest.mark.parametrize(
    "timezone",
    ["US/Pacific", "UTC", "Europe/Berlin", "Asia/Tokyo", "Pacific/Marquesas", "Asia/Katmandu"],
)
def test_can_patch_config(client: HttpClient, interval, timezone):
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
        "interval": interval,
    }

    organization = create_organization("Test Org")
    team = create_team(organization, timezone=timezone)
    user = create_user("test@user.com", "Test User", organization)
    client.force_login(user)

    with start_test_worker(temporal):
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
        batch_export = get_batch_export_ok(client, team.pk, batch_export["id"])
        assert batch_export["interval"] == interval
        assert batch_export["destination"]["config"]["bucket_name"] == "my-new-production-s3-bucket"

        # validate the underlying temporal schedule has been updated
        codec = EncryptionCodec(settings=settings)
        new_schedule = describe_schedule(temporal, batch_export["id"])
        assert old_schedule.schedule.spec.intervals[0].every == new_schedule.schedule.spec.intervals[0].every
        decoded_payload = async_to_sync(codec.decode)(new_schedule.schedule.action.args)
        args = json.loads(decoded_payload[0].data)
        assert args["bucket_name"] == "my-new-production-s3-bucket"
        assert new_schedule.schedule.spec.time_zone_name == old_schedule.schedule.spec.time_zone_name == timezone


@pytest.mark.django_db
@pytest.mark.parametrize("interval", ["hour", "day"])
def test_can_patch_config_with_invalid_old_values(client: HttpClient, interval):
    temporal = sync_connect()

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

    organization = create_organization("Test Org")
    team = create_team(organization)
    user = create_user("test@user.com", "Test User", organization)
    client.force_login(user)

    # Create a BatchExport straight in the database/temporal to avoid going through the API
    # as that's what we are trying to test here.
    destination = BatchExportDestination(**destination_data)
    batch_export = BatchExport(team=team, destination=destination, **batch_export_data)

    sync_batch_export(batch_export, created=True)

    destination.save()
    batch_export.save()

    with start_test_worker(temporal):
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
        batch_export = get_batch_export_ok(client, team.pk, batch_export.id)
        assert batch_export["interval"] == interval
        assert batch_export["destination"]["config"]["bucket_name"] == "my-new-production-s3-bucket"

        # validate the underlying temporal schedule has been updated
        codec = EncryptionCodec(settings=settings)
        new_schedule = describe_schedule(temporal, batch_export["id"])
        decoded_payload = async_to_sync(codec.decode)(new_schedule.schedule.action.args)
        args = json.loads(decoded_payload[0].data)
        assert args["bucket_name"] == "my-new-production-s3-bucket"
        assert args.get("invalid_key", None) is None


def test_can_patch_hogql_query(client: HttpClient):
    """Test we can patch a schema with a HogQL query."""
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

        batch_export = get_batch_export_ok(client, team.pk, batch_export["id"])
        assert batch_export["interval"] == "hour"
        assert batch_export["destination"]["config"]["bucket_name"] == "my-production-s3-bucket"
        assert batch_export["schema"] == {
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


def test_patch_returns_error_on_unsupported_hogql_query(client: HttpClient):
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
        "start_at": "2023-07-19 00:00:00",
        "end_at": "2023-07-20 00:00:00",
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

        new_batch_export_data = {
            "name": "my-production-s3-bucket-destination",
            # toInt32 is not a supported HogQL function
            "hogql_query": "select toInt32(1+1) as n from events",
        }
        response = put_batch_export(client, team.pk, batch_export["id"], new_batch_export_data)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
