import datetime as dt
import json
from unittest import mock

import pytest
from asgiref.sync import async_to_sync
from django.conf import settings
from django.test.client import Client as HttpClient
from rest_framework import status

from posthog.api.test.batch_exports.conftest import describe_schedule, start_test_worker
from posthog.api.test.batch_exports.fixtures import create_organization
from posthog.api.test.batch_exports.operations import create_batch_export
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.batch_exports.models import BatchExport
from posthog.temporal.common.codec import EncryptionCodec

pytestmark = [
    pytest.mark.django_db,
]


@pytest.mark.parametrize("interval", ["hour", "day", "every 5 minutes"])
def test_create_batch_export_with_interval_schedule(client: HttpClient, interval, temporal):
    """Test creating a BatchExport.

    When creating a BatchExport, we should create a corresponding Schedule in
    Temporal as described by the associated BatchExportSchedule model. In this
    test we assert this Schedule is created in Temporal and populated with the
    expected inputs.
    """

    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": "my-production-s3-bucket",
            "region": "us-east-1",
            "prefix": "posthog-events/",
            "aws_access_key_id": "abc123",
            "aws_secret_access_key": "secret",
            "use_virtual_style_addressing": True,
        },
    }

    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": interval,
    }

    organization = create_organization("Test Org")
    team = create_team(organization)
    user = create_user("test@user.com", "Test User", organization)
    client.force_login(user)

    with start_test_worker(temporal):
        with mock.patch(
            "posthog.batch_exports.http.posthoganalytics.feature_enabled",
            return_value=True,
        ) as feature_enabled:
            response = create_batch_export(
                client,
                team.pk,
                batch_export_data,
            )

        if interval == "every 5 minutes":
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
        codec = EncryptionCodec(settings=settings)
        schedule = describe_schedule(temporal, data["id"])

        batch_export = BatchExport.objects.get(id=data["id"])
        assert schedule.schedule.spec.intervals[0].every == batch_export.interval_time_delta
        assert schedule.schedule.spec.jitter == batch_export.jitter

        decoded_payload = async_to_sync(codec.decode)(schedule.schedule.action.args)
        args = json.loads(decoded_payload[0].data)

        # Common inputs
        assert args["team_id"] == team.pk
        assert args["batch_export_id"] == data["id"]
        assert args["interval"] == interval

        if interval == "hour":
            assert batch_export.jitter == dt.timedelta(minutes=15)
        elif interval == "day":
            assert batch_export.jitter == dt.timedelta(hours=1)
        elif interval == "every 5 minutes":
            assert batch_export.jitter == dt.timedelta(minutes=1)

        # S3 specific inputs
        assert args["bucket_name"] == "my-production-s3-bucket"
        assert args["region"] == "us-east-1"
        assert args["prefix"] == "posthog-events/"
        assert args["aws_access_key_id"] == "abc123"
        assert args["aws_secret_access_key"] == "secret"
        assert args["use_virtual_style_addressing"]


@pytest.mark.parametrize(
    "timezone",
    ["US/Pacific", "UTC", "Europe/Berlin", "Asia/Tokyo", "Pacific/Marquesas", "Asia/Katmandu"],
)
def test_create_batch_export_with_different_team_timezones(client: HttpClient, timezone: str, temporal):
    """Test creating a BatchExport.

    When creating a BatchExport, we should create a corresponding Schedule in
    Temporal as described by the associated BatchExportSchedule model. In this
    test we assert this Schedule is created in Temporal with the Team's timezone.
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

    organization = create_organization("Test Org")
    team = create_team(organization, timezone=timezone)
    user = create_user("test@user.com", "Test User", organization)
    client.force_login(user)

    with start_test_worker(temporal):
        response = create_batch_export(
            client,
            team.pk,
            batch_export_data,
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()

        data = response.json()
        schedule = describe_schedule(temporal, data["id"])
        intervals = schedule.schedule.spec.intervals

        assert len(intervals) == 1
        assert schedule.schedule.spec.intervals[0].every == dt.timedelta(days=1)
        assert schedule.schedule.spec.time_zone_name == timezone


def test_cannot_create_a_batch_export_for_another_organization(client: HttpClient, temporal):
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
    create_team(organization)
    user = create_user("test@user.com", "Test User", organization)

    another_organization = create_organization("Another Test Org")
    another_team = create_team(another_organization)

    with start_test_worker(temporal):
        client.force_login(user)
        response = create_batch_export(
            client,
            another_team.pk,
            batch_export_data,
        )

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()


def test_cannot_create_a_batch_export_with_higher_frequencies_if_not_enabled(client: HttpClient, temporal):
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
        "interval": "every 5 minutes",
    }

    organization = create_organization("Test Org")
    team = create_team(organization)
    user = create_user("test@user.com", "Test User", organization)

    with start_test_worker(temporal):
        client.force_login(user)
        with mock.patch(
            "posthog.batch_exports.http.posthoganalytics.feature_enabled",
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


def test_create_batch_export_with_custom_schema(client: HttpClient, temporal):
    """Test creating a BatchExport with a custom schema expressed as a HogQL Query.

    When creating a BatchExport, we should create a corresponding Schedule in
    Temporal as described by the associated BatchExportSchedule model. In this
    test we assert this Schedule is created in Temporal and populated with the
    expected inputs.
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
        "hogql_query": TEST_HOGQL_QUERY,
        "interval": "hour",
    }

    organization = create_organization("Test Org")
    team = create_team(organization)
    user = create_user("test@user.com", "Test User", organization)
    client.force_login(user)

    with start_test_worker(temporal):
        response = create_batch_export(
            client,
            team.pk,
            batch_export_data,
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()

        data = response.json()
        expected_hogql_query = " ".join(TEST_HOGQL_QUERY.split())  # Don't care about whitespace
        assert data["schema"]["hogql_query"] == expected_hogql_query

        codec = EncryptionCodec(settings=settings)
        schedule = describe_schedule(temporal, data["id"])

        batch_export = BatchExport.objects.get(id=data["id"])

        decoded_payload = async_to_sync(codec.decode)(schedule.schedule.action.args)
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
    "invalid_query",
    [
        "SELECT",
        "SELECT event,, FROM events",
        "SELECT unknown_field FROM events",
        "SELECT event, persons.id FROM events LEFT JOIN persons ON events.person_id = persons.id",
        "SELECT event FROM events UNION ALL SELECT event FROM events",
    ],
)
def test_create_batch_export_fails_with_invalid_query(client: HttpClient, invalid_query, temporal):
    """Test creating a BatchExport should fail with an invalid query."""

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
        "hogql_query": invalid_query,
    }

    organization = create_organization("Test Org")
    team = create_team(organization)
    user = create_user("test@user.com", "Test User", organization)
    client.force_login(user)

    with start_test_worker(temporal):
        response = create_batch_export(
            client,
            team.pk,
            batch_export_data,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()


@pytest.mark.parametrize(
    "auth_type,credentials,expected_status",
    [
        # Password auth type tests
        (
            "password",
            {"password": "abc123"},
            status.HTTP_201_CREATED,
        ),
        (
            "password",
            {},
            status.HTTP_400_BAD_REQUEST,
        ),
        # Key pair auth type tests
        (
            "keypair",
            {"private_key": "SECRET_KEY"},
            status.HTTP_201_CREATED,
        ),
        (
            "keypair",
            {},
            status.HTTP_400_BAD_REQUEST,
        ),
    ],
)
def test_create_snowflake_batch_export_validates_credentials(
    client: HttpClient, auth_type, credentials, expected_status, temporal
):
    """Test creating a BatchExport with Snowflake destination validates credentials based on auth type."""

    destination_data = {
        "type": "Snowflake",
        "config": {
            "account": "my-account",
            "user": "user",
            "database": "my-db",
            "warehouse": "COMPUTE_WH",
            "schema": "public",
            "table_name": "my_events",
            "authentication_type": auth_type,
            **credentials,
        },
    }

    batch_export_data = {
        "name": "my-production-snowflake-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    organization = create_organization("Test Org")
    team = create_team(organization)
    user = create_user("test@user.com", "Test User", organization)
    client.force_login(user)

    with start_test_worker(temporal):
        response = create_batch_export(
            client,
            team.pk,
            batch_export_data,
        )

        assert response.status_code == expected_status

        if expected_status == status.HTTP_400_BAD_REQUEST:
            if auth_type == "password":
                assert "Password is required if authentication type is password" in response.json()["detail"]
            else:
                assert "Private key is required if authentication type is key pair" in response.json()["detail"]


@pytest.mark.parametrize(
    "file_format,compression,expected_error_message",
    [
        (
            "JSONLines",
            None,
            None,
        ),
        (
            "JSONLines",
            "gzip",
            None,
        ),
        (
            "JSONLines",
            "zstd",
            "Compression zstd is not supported for file format JSONLines. Supported compressions are ['gzip', 'brotli']",
        ),
        (
            "Parquet",
            None,
            None,
        ),
        (
            "Parquet",
            "gzip",
            None,
        ),
        (
            "Parquet",
            "brotli",
            None,
        ),
        (
            "Parquet",
            "zstd",
            None,
        ),
        (
            "Parquet",
            "unknown",
            "Compression unknown is not supported for file format Parquet. Supported compressions are ['zstd', 'lz4', 'snappy', 'gzip', 'brotli']",
        ),
        (
            "unknown",
            "gzip",
            "File format unknown is not supported. Supported file formats are ['Parquet', 'JSONLines']",
        ),
    ],
)
def test_create_s3_batch_export_validates_file_format_and_compression(
    client: HttpClient, file_format, compression, expected_error_message, temporal
):
    """Test creating a BatchExport with S3 destination validates file format and compression."""

    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": "my-s3-bucket",
            "region": "us-east-1",
            "prefix": "posthog-events/",
            "aws_access_key_id": "abc123",
            "aws_secret_access_key": "secret",
            "file_format": file_format,
            "compression": compression,
        },
    }

    batch_export_data = {
        "name": "my-s3-bucket",
        "destination": destination_data,
        "interval": "hour",
    }

    organization = create_organization("Test Org")
    team = create_team(organization)
    user = create_user("test@user.com", "Test User", organization)
    client.force_login(user)

    with start_test_worker(temporal):
        response = create_batch_export(
            client,
            team.pk,
            batch_export_data,
        )

        if expected_error_message is None:
            assert response.status_code == status.HTTP_201_CREATED
        else:
            assert response.status_code == status.HTTP_400_BAD_REQUEST
            assert response.json()["detail"] == expected_error_message
