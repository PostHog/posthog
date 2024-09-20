import datetime as dt
import json
from unittest import mock

import pytest
from asgiref.sync import async_to_sync
from django.conf import settings
from django.test.client import Client as HttpClient
from rest_framework import status

from posthog.api.test.batch_exports.conftest import describe_schedule, start_test_worker
from posthog.api.test.batch_exports.operations import create_batch_export
from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.batch_exports.models import BatchExport
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.codec import EncryptionCodec

pytestmark = [
    pytest.mark.django_db,
]


@pytest.mark.parametrize("interval", ["hour", "day", "every 5 minutes"])
def test_create_batch_export_with_interval_schedule(client: HttpClient, interval):
    """Test creating a BatchExport.

    When creating a BatchExport, we should create a corresponding Schedule in
    Temporal as described by the associated BatchExportSchedule model. In this
    test we assert this Schedule is created in Temporal and populated with the
    expected inputs.
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

        decoded_payload = async_to_sync(codec.decode)(schedule.schedule.action.args)
        args = json.loads(decoded_payload[0].data)

        # Common inputs
        assert args["team_id"] == team.pk
        assert args["batch_export_id"] == data["id"]
        assert args["interval"] == interval

        # S3 specific inputs
        assert args["bucket_name"] == "my-production-s3-bucket"
        assert args["region"] == "us-east-1"
        assert args["prefix"] == "posthog-events/"
        assert args["aws_access_key_id"] == "abc123"
        assert args["aws_secret_access_key"] == "secret"


@pytest.mark.parametrize(
    "timezone",
    ["US/Pacific", "UTC", "Europe/Berlin", "Asia/Tokyo", "Pacific/Marquesas", "Asia/Katmandu"],
)
def test_create_batch_export_with_different_team_timezones(client: HttpClient, timezone: str):
    """Test creating a BatchExport.

    When creating a BatchExport, we should create a corresponding Schedule in
    Temporal as described by the associated BatchExportSchedule model. In this
    test we assert this Schedule is created in Temporal with the Team's timezone.
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


def test_cannot_create_a_batch_export_for_another_organization(client: HttpClient):
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


def test_cannot_create_a_batch_export_with_higher_frequencies_if_not_enabled(client: HttpClient):
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
  properties.custom AS custom
FROM events
"""


def test_create_batch_export_with_custom_schema(client: HttpClient):
    """Test creating a BatchExport with a custom schema expressed as a HogQL Query.

    When creating a BatchExport, we should create a corresponding Schedule in
    Temporal as described by the associated BatchExportSchedule model. In this
    test we assert this Schedule is created in Temporal and populated with the
    expected inputs.
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
        assert args["batch_export_model"] == {"name": "events", "schema": expected_schema}


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
def test_create_batch_export_fails_with_invalid_query(client: HttpClient, invalid_query):
    """Test creating a BatchExport should fail with an invalid query."""
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
