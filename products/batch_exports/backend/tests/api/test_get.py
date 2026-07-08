import pytest

from django.test.client import Client as HttpClient

from rest_framework import status

from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user

from products.batch_exports.backend.models.batch_export import BatchExport, BatchExportDestination
from products.batch_exports.backend.tests.api.fixtures import create_organization
from products.batch_exports.backend.tests.api.operations import create_batch_export_ok, get_batch_export

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("temporal_worker", "cleanup"),
]


@pytest.mark.parametrize(
    "interval,timezone,offset_day,offset_hour",
    [
        ("hour", "UTC", None, None),
        ("day", "UTC", None, None),
        ("day", "US/Pacific", None, 2),
        ("week", "UTC", 1, 0),
        ("week", "Asia/Kathmandu", 1, 2),
    ],
)
def test_can_get_exports_for_your_organizations(
    client: HttpClient, temporal, organization, team, user, interval, timezone, offset_day, offset_hour
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
        "interval": interval,
        "timezone": timezone,
        "offset_day": offset_day,
        "offset_hour": offset_hour,
    }

    client.force_login(user)

    response = create_batch_export_ok(
        client,
        team.pk,
        batch_export_data,
    )

    response = get_batch_export(client, team.pk, response["id"])
    assert response.status_code == status.HTTP_200_OK, response.json()

    batch_export = response.json()

    expected_offset_day = offset_day
    if interval == "week":
        expected_offset_day = expected_offset_day or 0

    expected_offset_hour = offset_hour
    if interval == "day" or interval == "week":
        expected_offset_hour = expected_offset_hour or 0

    # Check that the schedule info is returned correctly
    assert batch_export["interval"] == interval
    assert batch_export["timezone"] == timezone
    assert batch_export["offset_day"] == expected_offset_day
    assert batch_export["offset_hour"] == expected_offset_hour

    # Check that the destination config is returned, except for aws_access_key_id and aws_secret_access_key.
    assert batch_export["destination"]["config"] == {
        "bucket_name": "my-production-s3-bucket",
        "region": "us-east-1",
        "prefix": "posthog-events/",
    }


def test_cannot_get_exports_for_other_organizations(client: HttpClient, temporal, organization, team, user):
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

    another_organization = create_organization("Another Org")
    another_user = create_user("another-test@user.com", "Another Test User", another_organization)

    client.force_login(user)
    response = create_batch_export_ok(
        client,
        team.pk,
        batch_export_data,
    )

    client.force_login(another_user)
    response = get_batch_export(client, team.pk, response["id"])
    assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()


def test_batch_exports_are_partitioned_by_team(client: HttpClient, temporal, organization, team, user):
    """
    You shouldn't be able to fetch a BatchExport by id, via a team that it
    doesn't belong to.
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
        "interval": "hour",
    }

    another_team = create_team(organization)

    client.force_login(user)
    batch_export = create_batch_export_ok(
        client,
        team.pk,
        batch_export_data,
    )

    response = get_batch_export(client, another_team.pk, batch_export["id"])
    assert response.status_code == status.HTTP_404_NOT_FOUND, response.json()

    # And switch the teams around for good measure.
    batch_export = create_batch_export_ok(
        client,
        another_team.pk,
        batch_export_data,
    )

    response = get_batch_export(client, team.pk, batch_export["id"])
    assert response.status_code == status.HTTP_404_NOT_FOUND, response.json()


def test_serialization_of_destination_config(client: HttpClient, temporal, organization, team, user):
    """Test that the destination config is serialized correctly.

    Our destination config is encrypted using EncryptedJSONField, which decrypts most data types
    (including booleans) into strings. Therefore, we want to ensure these are serialized to their
    correct JSON types in the response.
    """
    destination_data = {
        "type": "Postgres",
        "config": {
            "host": "127.0.0.1",
            "port": 5432,
            "user": "test",
            "password": "test",
            "schema": "public",
            "database": "test",
            "table_name": "batch_export_events",
            "has_self_signed_cert": False,
        },
    }

    # Created via the ORM to exercise an inline-credential (legacy) Postgres export, which can no
    # longer be created through the API now that new Postgres exports require an integration.
    destination = BatchExportDestination.objects.create(
        type=BatchExportDestination.Destination.POSTGRES,
        config=destination_data["config"],
    )
    batch_export = BatchExport.objects.create(name="my-export", team=team, destination=destination, interval="day")

    client.force_login(user)
    response = get_batch_export(client, team.pk, batch_export.id)
    assert response.status_code == status.HTTP_200_OK, response.json()

    batch_export = response.json()

    # Check that the destination config is returned with correct JSON types, except for user and
    # password, which are sensitive
    assert batch_export["destination"]["config"] == {
        "host": "127.0.0.1",
        "port": 5432,
        "schema": "public",
        "database": "test",
        "table_name": "batch_export_events",
        "has_self_signed_cert": False,
    }
