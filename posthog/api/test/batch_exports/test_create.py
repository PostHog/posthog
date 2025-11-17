import json
import datetime as dt

import pytest
from unittest import mock

from django.conf import settings
from django.test.client import Client as HttpClient

from asgiref.sync import async_to_sync
from rest_framework import status
from temporalio.client import ScheduleActionStartWorkflow

from posthog.api.test.batch_exports.conftest import describe_schedule
from posthog.api.test.batch_exports.fixtures import create_organization
from posthog.api.test.batch_exports.operations import create_batch_export
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.batch_exports.models import BatchExport
from posthog.models.integration import Integration
from posthog.temporal.common.codec import EncryptionCodec

pytestmark = [
    pytest.mark.django_db,
]


@pytest.mark.parametrize("interval", ["hour", "day", "every 5 minutes"])
def test_create_batch_export_with_interval_schedule(client: HttpClient, interval, temporal, organization, team, user):
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
        "integration": None,
    }

    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": interval,
    }

    client.force_login(user)

    with mock.patch(
        "posthog.batch_exports.http.posthoganalytics.feature_enabled",
        return_value=True,
    ):
        response = create_batch_export(
            client,
            team.pk,
            batch_export_data,
        )

    # TODO: Removed while `managed-viewsets` feature flag is active since this messes up this check
    # This can be uncommented once the `managed-viewsets` feature flag is fully rolled out
    # if interval == "every 5 minutes":
    #     feature_enabled.assert_called_once_with(
    #         "high-frequency-batch-exports",
    #         str(team.uuid),
    #         groups={"organization": str(team.organization.id)},
    #         group_properties={
    #             "organization": {
    #                 "id": str(team.organization.id),
    #                 "created_at": team.organization.created_at,
    #             }
    #         },
    #         send_feature_flag_events=False,
    #     )

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
def test_create_batch_export_with_different_team_timezones(client: HttpClient, timezone: str, temporal, organization):
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

    team = create_team(organization, timezone=timezone)
    user = create_user("test@user.com", "Test User", organization)
    client.force_login(user)

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


def test_cannot_create_a_batch_export_for_another_organization(client: HttpClient, temporal, organization, user):
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


def test_cannot_create_a_batch_export_with_higher_frequencies_if_not_enabled(
    client: HttpClient, temporal, organization, team, user
):
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


def test_create_batch_export_with_custom_schema(client: HttpClient, temporal, organization, team, user):
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
        ("WITH cte AS (SELECT event FROM events) SELECT event FROM cte", "Subqueries or CTEs are not supported"),
        ("SELECT event FROM (SELECT event FROM events)", "Subqueries or CTEs are not supported"),
    ],
)
def test_create_batch_export_fails_with_invalid_query(
    client: HttpClient, invalid_query, expected_error_message, temporal, organization, team, user
):
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

    client.force_login(user)

    response = create_batch_export(
        client,
        team.pk,
        batch_export_data,
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert response.json()["detail"] == expected_error_message


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
    client: HttpClient, auth_type, credentials, expected_status, temporal, organization, team, user
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

    client.force_login(user)

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
    "mode,copy_inputs,expected_status",
    [
        (
            "INSERT",
            {},
            status.HTTP_201_CREATED,
        ),
        (
            "INSERT",
            None,
            status.HTTP_201_CREATED,
        ),
        (
            "COPY",
            {
                "s3_bucket": "my-production-s3-bucket",
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": {"aws_access_key_id": "abc123", "aws_secret_access_key": "secret"},
                "authorization": "default",
            },
            status.HTTP_201_CREATED,
        ),
        (
            "COPY",
            {
                "s3_bucket": "my-production-s3-bucket",
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": {"aws_access_key_id": "abc123", "aws_secret_access_key": "secret"},
                "authorization": {"aws_access_key_id": "abc123", "aws_secret_access_key": "secret"},
            },
            status.HTTP_201_CREATED,
        ),
        # Missing required 's3_bucket'
        (
            "COPY",
            {
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": {"aws_access_key_id": "abc123", "aws_secret_access_key": "secret"},
                "authorization": "default",
            },
            status.HTTP_400_BAD_REQUEST,
        ),
        # Missing required 'region_name'
        (
            "COPY",
            {
                "s3_bucket": "my-production-s3-bucket",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": {"aws_access_key_id": "abc123", "aws_secret_access_key": "secret"},
                "authorization": "default",
            },
            status.HTTP_400_BAD_REQUEST,
        ),
        # Missing required 'aws_secret_access_key' in 'bucket_credentials
        (
            "COPY",
            {
                "s3_bucket": "my-production-s3-bucket",
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": {"aws_access_key_id": "abc123"},
                "authorization": "default",
            },
            status.HTTP_400_BAD_REQUEST,
        ),
        # Empty 'bucket_credentials'
        (
            "COPY",
            {
                "s3_bucket": "my-production-s3-bucket",
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": {},
                "authorization": "default",
            },
            status.HTTP_400_BAD_REQUEST,
        ),
        # Empty 'authorization'
        (
            "COPY",
            {
                "s3_bucket": "my-production-s3-bucket",
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": {"aws_access_key_id": "abc123", "aws_secret_access_key": "secret"},
                "authorization": {},
            },
            status.HTTP_400_BAD_REQUEST,
        ),
        # Empty 'authorization' as IAMRole
        (
            "COPY",
            {
                "s3_bucket": "my-production-s3-bucket",
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": {"aws_access_key_id": "abc123", "aws_secret_access_key": "secret"},
                "authorization": "",
            },
            status.HTTP_400_BAD_REQUEST,
        ),
    ],
)
def test_create_redshift_batch_export_validates_copy_inputs(
    client: HttpClient, mode, copy_inputs, expected_status, temporal, organization, team, user
):
    """Test creating a BatchExport with Redshift destination validates inputs for 'COPY'."""

    destination_data = {
        "type": "Redshift",
        "config": {
            "user": "user",
            "password": "my-password",
            "database": "my-db",
            "host": "test",
            "schema": "public",
            "table_name": "my_events",
            "mode": mode,
            "copy_inputs": copy_inputs,
        },
    }

    batch_export_data = {
        "name": "my-production-redshiftn-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)

    response = create_batch_export(
        client,
        team.pk,
        batch_export_data,
    )

    assert response.status_code == expected_status, response.json()

    if expected_status == status.HTTP_400_BAD_REQUEST:
        assert "Missing required" in response.json()["detail"]


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
    client: HttpClient, file_format, compression, expected_error_message, temporal, organization, team, user
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

    client.force_login(user)

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
            "S3",
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
                "host": "host",
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
def enable_databricks(team):
    with mock.patch("posthog.batch_exports.http.posthoganalytics.feature_enabled", return_value=True):
        yield

        # TODO: Removed while `managed-viewsets` feature flag is active since this messes up this check
        # This can be uncommented once the `managed-viewsets` feature flag is fully rolled out
        # feature_enabled.assert_called_once_with(
        #     "databricks-batch-exports",
        #     str(team.uuid),
        #     groups={"organization": str(team.organization.id)},
        #     group_properties={
        #         "organization": {
        #             "id": str(team.organization.id),
        #             "created_at": team.organization.created_at,
        #         }
        #     },
        #     send_feature_flag_events=False,
        # )


def test_creating_databricks_batch_export_using_integration(
    client: HttpClient, temporal, organization, team, user, databricks_integration, enable_databricks
):
    """Test that we can create a Databricks batch export using an integration.

    Using integrations is the preferred way to handle credentials for batch exports going forward.
    """

    destination_data = {
        "type": "Databricks",
        "config": {
            "http_path": "my-http-path",
            "catalog": "my-catalog",
            "schema": "my-schema",
            "table_name": "my-table-name",
        },
        "integration": databricks_integration.id,
    }

    batch_export_data = {
        "name": "my-databricks-destination",
        "destination": destination_data,
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
    assert data["destination"] == destination_data

    schedule = describe_schedule(temporal, data["id"])
    intervals = schedule.schedule.spec.intervals

    assert len(intervals) == 1
    assert schedule.schedule.spec.intervals[0].every == dt.timedelta(hours=1)
    assert isinstance(schedule.schedule.action, ScheduleActionStartWorkflow)
    assert schedule.schedule.action.workflow == "databricks-export"


def test_creating_databricks_batch_export_fails_if_feature_flag_is_not_enabled(
    client: HttpClient, temporal, organization, team, user, databricks_integration
):
    """Test that creating a Databricks batch export fails if the feature flag is not enabled."""

    destination_data = {
        "type": "Databricks",
        "config": {
            "http_path": "my-http-path",
            "catalog": "my-catalog",
            "schema": "my-schema",
            "table_name": "my-table-name",
        },
        "integration": databricks_integration.id,
    }

    batch_export_data = {
        "name": "my-databricks-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)

    response = create_batch_export(
        client,
        team.pk,
        batch_export_data,
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
    assert "The Databricks destination is not enabled for this team." in response.json()["detail"]


def test_creating_databricks_batch_export_fails_if_integration_is_missing(
    client: HttpClient, temporal, organization, team, user, enable_databricks
):
    """Test that creating a Databricks batch export fails if the integration is missing.

    Using integrations is the preferred way to handle credentials for batch exports going forward.
    """

    destination_data = {
        "type": "Databricks",
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
    response = create_batch_export(
        client,
        team.pk,
        batch_export_data,
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    assert response.json() == {
        "type": "validation_error",
        "code": "invalid_input",
        "detail": "Integration is required for Databricks batch exports",
        "attr": "destination",
    }


def test_creating_databricks_batch_export_fails_if_integration_is_invalid(
    client: HttpClient, temporal, organization, team, user, enable_databricks
):
    """Test that creating a Databricks batch export fails if the integration is invalid.

    Using integrations is the preferred way to handle credentials for batch exports going forward.

    In this case, the integration is missing the client_secret. In theory, this shouldn't happen, as we validate the
    integration when creating it via the API.
    """

    integration = Integration.objects.create(
        team=team,
        kind=Integration.IntegrationKind.DATABRICKS,
        integration_id="my-server-hostname",
        config={"server_hostname": "my-server-hostname"},
        sensitive_config={"client_id": "my-client-id"},
        created_by=user,
    )

    destination_data = {
        "type": "Databricks",
        "config": {
            "http_path": "my-http-path",
            "catalog": "my-catalog",
            "schema": "my-schema",
            "table_name": "my-table-name",
        },
        "integration": integration.pk,
    }

    batch_export_data = {
        "name": "my-databricks-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)
    response = create_batch_export(
        client,
        team.pk,
        batch_export_data,
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert response.json()["detail"] == "Databricks integration is not valid: 'client_secret' missing"


def test_creating_databricks_batch_export_fails_if_integration_does_not_exist(
    client: HttpClient,
    temporal,
    organization,
    team,
    user,
):
    """Test that creating a Databricks batch export fails if the integration does not exist in the database.

    Using integrations is the preferred way to handle credentials for batch exports going forward.
    """

    destination_data = {
        "type": "Databricks",
        "config": {
            "http_path": "my-http-path",
            "catalog": "my-catalog",
            "schema": "my-schema",
            "table_name": "my-table-name",
        },
        "integration": 999,
    }

    batch_export_data = {
        "name": "my-databricks-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)
    response = create_batch_export(
        client,
        team.pk,
        batch_export_data,
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    assert response.json() == {
        "type": "validation_error",
        "code": "does_not_exist",
        "detail": 'Invalid pk "999" - object does not exist.',
        "attr": "destination__integration",
    }


def test_creating_databricks_batch_export_fails_if_integration_is_not_the_correct_type(
    client: HttpClient, temporal, organization, team, user, enable_databricks
):
    """Test that creating a Databricks batch export fails if the integration is not the correct type.

    Using integrations is the preferred way to handle credentials for batch exports going forward.

    In this case, the integration is not a Databricks integration.
    """

    integration = Integration.objects.create(
        team=team,
        kind=Integration.IntegrationKind.SLACK,
        integration_id="my-server-hostname",
        config={"server_hostname": "my-server-hostname"},
        sensitive_config={"client_id": "my-client-id"},
        created_by=user,
    )

    destination_data = {
        "type": "Databricks",
        "config": {
            "http_path": "my-http-path",
            "catalog": "my-catalog",
            "schema": "my-schema",
            "table_name": "my-table-name",
        },
        "integration": integration.pk,
    }

    batch_export_data = {
        "name": "my-databricks-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)
    response = create_batch_export(
        client,
        team.pk,
        batch_export_data,
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert response.json()["detail"] == "Integration is not a Databricks integration."


@pytest.mark.parametrize(
    "model,expected_status,expected_error",
    [
        ("events", status.HTTP_201_CREATED, None),
        (None, status.HTTP_201_CREATED, None),
        ("persons", status.HTTP_400_BAD_REQUEST, "HTTP batch exports only support the events model"),
    ],
)
def test_creating_http_batch_export_only_allows_events_model(
    client: HttpClient, temporal, organization, team, user, model, expected_status, expected_error
):
    """HTTP batch exports are used for migrations, and therefore only support the events model."""

    destination_data = {
        "type": "HTTP",
        "config": {
            "url": "https://test.i.posthog.com/batch/",
            "token": "secret-token",
        },
    }

    batch_export_data = {
        "name": "my-http-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    if model is not None:
        batch_export_data["model"] = model

    client.force_login(user)
    response = create_batch_export(
        client,
        team.pk,
        batch_export_data,
    )

    assert response.status_code == expected_status, response.json()

    if expected_error:
        assert response.json()["detail"] == expected_error


@pytest.mark.parametrize(
    "type,filters,config,expected_status,expected_error",
    [
        (
            "BigQuery",
            {"filters": {"filter_something": 123}},
            {
                "project_id": "test",
                "dataset_id": "test",
                "private_key": "pkey",
                "private_key_id": "pkey_id",
                "token_uri": "token",
                "client_email": "email",
            },
            status.HTTP_400_BAD_REQUEST,
            "should be an array",
        ),
        (
            "BigQuery",
            None,
            {
                "project_id": "test",
                "dataset_id": "test",
                "private_key": "pkey",
                "private_key_id": "pkey_id",
                "token_uri": "token",
                "client_email": "email",
            },
            status.HTTP_201_CREATED,
            None,
        ),
        (
            "BigQuery",
            [],
            {
                "project_id": "test",
                "dataset_id": "test",
                "private_key": "pkey",
                "private_key_id": "pkey_id",
                "token_uri": "token",
                "client_email": "email",
            },
            status.HTTP_201_CREATED,
            None,
        ),
        (
            "S3",
            [{"data_interval_start": "2025-01-01"}],
            {
                "bucket_name": "my-s3-bucket",
                "region": "us-east-1",
                "prefix": "posthog-events/",
                "aws_access_key_id": "abc123",
                "aws_secret_access_key": "secret",
            },
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
    type,
    filters,
    config,
    expected_status,
    expected_error,
):
    """Test validation of the filters field when creating a batch export."""

    destination_data = {
        "type": type,
        "config": config,
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
