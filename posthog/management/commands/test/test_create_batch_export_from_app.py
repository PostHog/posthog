import json
import uuid
import typing
import datetime as dt
import collections

import pytest

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

from asgiref.sync import async_to_sync

from posthog.api.test.batch_exports.conftest import describe_schedule
from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.management.commands.create_batch_export_from_app import map_plugin_config_to_destination
from posthog.models import Plugin, PluginAttachment, PluginConfig
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.codec import EncryptionCodec


@pytest.fixture
def organization():
    organization = create_organization("test")
    yield organization
    organization.delete()


@pytest.fixture
def team(organization):
    team = create_team(organization=organization)
    yield team
    team.delete()


# Used to randomize plugin URLs, to prevent tests stepping on each other, since
# plugin urls are constrained to be unique.
def append_random(url: str) -> str:
    return f"{url}?random={uuid.uuid4()}"


@pytest.fixture
def snowflake_plugin(organization) -> typing.Generator[Plugin, None, None]:
    plugin = Plugin.objects.create(
        name="Snowflake Export",
        url=append_random("https://github.com/PostHog/snowflake-export-plugin"),
        plugin_type="custom",
        organization=organization,
    )
    yield plugin
    plugin.delete()


@pytest.fixture
def s3_plugin(organization) -> typing.Generator[Plugin, None, None]:
    plugin = Plugin.objects.create(
        name="S3 Export Plugin",
        url=append_random("https://github.com/PostHog/s3-export-plugin"),
        plugin_type="custom",
        organization=organization,
    )
    yield plugin
    plugin.delete()


@pytest.fixture
def bigquery_plugin(organization) -> typing.Generator[Plugin, None, None]:
    plugin = Plugin.objects.create(
        name="BigQuery Export",
        url=append_random("https://github.com/PostHog/bigquery-plugin"),
        plugin_type="custom",
        organization=organization,
    )
    yield plugin
    plugin.delete()


@pytest.fixture
def postgres_plugin(organization) -> typing.Generator[Plugin, None, None]:
    plugin = Plugin.objects.create(
        name="PostgreSQL Export Plugin",
        url=append_random("https://github.com/PostHog/postgres-plugin"),
        plugin_type="custom",
        organization=organization,
    )
    yield plugin
    plugin.delete()


@pytest.fixture
def redshift_plugin(organization) -> typing.Generator[Plugin, None, None]:
    plugin = Plugin.objects.create(
        name="Redshift Export Plugin",
        url=append_random("https://github.com/PostHog/postgres-plugin"),
        plugin_type="custom",
        organization=organization,
    )
    yield plugin
    plugin.delete()


test_snowflake_config: dict[str, typing.Any] = {
    "account": "snowflake-account",
    "username": "test-user",
    "password": "test-password",
    "warehouse": "test-warehouse",
    "database": "test-db",
    "dbschema": "test-schema",
    "table": "test-table",
    "role": "test-role",
}
test_s3_config: dict[str, typing.Any] = {
    "awsAccessKey": "access-key",
    "awsSecretAccessKey": "secret-access-key",
    "s3BucketName": "test-bucket",
    "awsRegion": "eu-central-1",
    "prefix": "posthog/",
    "compression": "gzip",
    "eventsToIgnore": "$feature_flag_called",
}
test_bigquery_config: dict[str, typing.Any] = {
    "tableId": "my_table_id",
    "datasetId": "my_dataset_id",
    "googleCloudKeyJson": {
        "type": "service_accout",
        "project_id": "my_project_id",
        "private_key_id": "my_private_key_id",
        "private_key": "-----BEGIN PRIVATE KEY-----Wow much private, such key-----END PRIVATE KEY-----",
        "client_email": "email@google.com",
        "client_id": "client_id",
        "auth_uri": "https://accouts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata",
    },
    "exportEventsToIgnore": "$feature_flag_called,$pageleave,$pageview,$rageclick,$identify",
}
test_postgres_config: dict[str, typing.Any] = {
    "host": "localhost",
    "port": "5432",
    "dbName": "dev",
    "tableName": "posthog_event",
    "dbPassword": "password",
    "dbUsername": "username",
    "databaseUrl": "",
    "eventsToIgnore": "$feature_flag_called",
    "hasSelfSignedCert": "Yes",
}
test_postgres_config_with_database_url: dict[str, typing.Any] = {
    "port": "54322",
    "dbName": "prod",
    "host": "localhost",
    "tableName": "posthog_event",
    "dbPassword": "password_in_url",
    "dbUsername": "username_in_url",
    "databaseUrl": "postgres://username_in_url:password_in_url@localhost:54322/prod",
    "eventsToIgnore": "$feature_flag_called,$pageleave,$pageview,$rageclick,$identify",
    "hasSelfSignedCert": "Yes",
}
test_redshift_config: dict[str, typing.Any] = {
    "clusterHost": "localhost",
    "clusterPort": "5439",
    "dbName": "dev",
    "tableName": "posthog_event",
    "dbPassword": "password",
    "dbUsername": "username",
    "eventsToIgnore": "$feature_flag_called",
    "propertiesDataType": "super",
}

PluginConfigParams = collections.namedtuple(
    "PluginConfigParams", ("plugin_type", "disabled", "database_url"), defaults=(False, False)
)


@pytest.fixture
def config(request) -> dict[str, typing.Any]:
    """Dispatch into one of the configurations for testing according to export/plugin type."""
    if isinstance(request.param, tuple):
        params = PluginConfigParams(*request.param)
    else:
        params = PluginConfigParams(request.param)

    match params.plugin_type:
        case "S3":
            return test_s3_config
        case "Snowflake":
            return test_snowflake_config
        case "BigQuery":
            return test_bigquery_config
        case "Postgres":
            if params.database_url is True:
                return test_postgres_config_with_database_url
            else:
                return test_postgres_config
        case "Redshift":
            return test_redshift_config
        case _:
            raise ValueError(f"Unsupported plugin: {request.param}")


@pytest.fixture
def plugin_config(
    request, bigquery_plugin, postgres_plugin, s3_plugin, snowflake_plugin, team, redshift_plugin
) -> typing.Generator[PluginConfig, None, None]:
    """Manage a PluginConfig for testing.

    We dispatch to each supported plugin/export type according to
    request.param.
    """
    if isinstance(request.param, tuple):
        params = PluginConfigParams(*request.param)
    else:
        params = PluginConfigParams(request.param)

    attachment_contents = None
    attachment_key = None

    match params.plugin_type:
        case "S3":
            plugin = s3_plugin
            config = test_s3_config
        case "Snowflake":
            plugin = snowflake_plugin
            config = test_snowflake_config
        case "BigQuery":
            plugin = bigquery_plugin
            config = test_bigquery_config

            json_attachment = config["googleCloudKeyJson"]
            attachment_contents = json.dumps(json_attachment).encode("utf-8")
            attachment_key = "googleCloudKeyJson"

            # Merge these back so that we can assert their prescense later.
            config = {**config, **json_attachment}

        case "Postgres":
            plugin = postgres_plugin

            if params.database_url is True:
                config = test_postgres_config_with_database_url
            else:
                config = test_postgres_config

        case "Redshift":
            plugin = redshift_plugin
            config = test_redshift_config

        case _:
            raise ValueError(f"Unsupported plugin: {params.plugin_type}")

    plugin_config = PluginConfig.objects.create(
        plugin=plugin,
        order=1,
        team=team,
        enabled=True,
        config=config,
    )

    attachment = None
    if attachment_contents and attachment_key:
        attachment = PluginAttachment.objects.create(
            key=attachment_key,
            plugin_config=plugin_config,
            team=team,
            contents=attachment_contents,
            file_size=len(attachment_contents),
            file_name=attachment_key,
        )

    if params.disabled is True:
        plugin_config.enabled = False
        plugin_config.save()

    yield plugin_config

    plugin_config.delete()

    if attachment:
        attachment.delete()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "plugin_config,config,expected_type",
    [
        ("S3", "S3", "S3"),
        ("Snowflake", "Snowflake", "Snowflake"),
        ("BigQuery", "BigQuery", "BigQuery"),
        ("Postgres", "Postgres", "Postgres"),
        (("Postgres", False, True), ("Postgres", False, True), "Postgres"),
        ("Redshift", "Redshift", "Redshift"),
    ],
    indirect=["plugin_config", "config"],
)
def test_map_plugin_config_to_destination(plugin_config, config, expected_type):
    """Test we are mapping PluginConfig to the correct destination type and values."""
    export_type, export_config = map_plugin_config_to_destination(plugin_config)

    assert export_type == expected_type

    result_values = list(export_config.values())
    for key, value in config.items():
        if key == "eventsToIgnore" or key == "exportEventsToIgnore":
            assert value.split(",") == export_config["exclude_events"]
            continue

        if key == "hasSelfSignedCert":
            assert (value == "Yes") == export_config["has_self_signed_cert"]
            continue

        if key in ("port", "clusterPort"):
            value = int(value)

        if key in (
            "databaseUrl",
            "googleCloudKeyJson",
        ):
            # We don't use these in exports, or we parse them and store them with a different key.
            continue

        assert value in result_values


@pytest.mark.django_db
@pytest.mark.parametrize(
    "plugin_config",
    ("S3", "Snowflake", "BigQuery", "Postgres", ("Postgres", False, True), "Redshift"),
    indirect=True,
)
def test_create_batch_export_from_app_fails_with_mismatched_team_id(plugin_config):
    """Test the create_batch_export_from_app command fails if team_id does not match PluginConfig.team_id."""

    with pytest.raises(CommandError):
        call_command(
            "create_batch_export_from_app",
            "--name='BatchExport'",
            f"--plugin-config-id={plugin_config.id}",
            "--team-id=0",
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "plugin_config",
    ("S3", "Snowflake", "BigQuery", "Postgres", ("Postgres", False, True), "Redshift"),
    indirect=True,
)
def test_create_batch_export_from_app_dry_run(plugin_config):
    """Test a dry_run of the create_batch_export_from_app command."""
    output = call_command(
        "create_batch_export_from_app",
        f"--plugin-config-id={plugin_config.id}",
        f"--team-id={plugin_config.team.id}",
        "--dry-run",
    )
    export_type, config = map_plugin_config_to_destination(plugin_config)

    batch_export_data = json.loads(output)

    assert "id" not in batch_export_data
    assert batch_export_data["team_id"] == plugin_config.team.id
    assert batch_export_data["interval"] == "hour"
    assert batch_export_data["name"] == f"{export_type} Export"
    assert batch_export_data["destination_data"] == {
        "type": export_type,
        "config": config,
    }


@pytest.mark.django_db
@pytest.mark.parametrize("interval", ("hour", "day"))
@pytest.mark.parametrize(
    "plugin_config",
    (
        ("S3", False),
        ("Snowflake", False),
        ("BigQuery", False),
        ("Redshift", False),
        ("Postgres", False),
        ("Postgres", False, True),
    ),
    indirect=True,
)
@pytest.mark.parametrize("disable_plugin_config", (True, False))
def test_create_batch_export_from_app(
    interval,
    plugin_config,
    disable_plugin_config,
):
    """Test a live run of the create_batch_export_from_app command."""
    args = [
        f"--plugin-config-id={plugin_config.id}",
        f"--team-id={plugin_config.team.id}",
        f"--interval={interval}",
    ]
    if disable_plugin_config:
        args.append("--disable-plugin-config")

    output = call_command("create_batch_export_from_app", *args)

    plugin_config.refresh_from_db()
    assert plugin_config.enabled is not disable_plugin_config

    export_type, config = map_plugin_config_to_destination(plugin_config)

    batch_export_data = json.loads(output)

    assert batch_export_data["team_id"] == plugin_config.team.id
    assert batch_export_data["interval"] == interval
    assert batch_export_data["name"] == f"{export_type} Export"
    assert batch_export_data["destination_data"] == {
        "type": export_type,
        "config": config,
    }

    temporal = sync_connect()

    schedule = describe_schedule(temporal, str(batch_export_data["id"]))
    expected_interval = dt.timedelta(**{f"{interval}s": 1})
    assert schedule.schedule.spec.intervals[0].every == expected_interval

    codec = EncryptionCodec(settings=settings)
    decoded_payload = async_to_sync(codec.decode)(schedule.schedule.action.args)
    input_args = json.loads(decoded_payload[0].data)

    # Common inputs
    assert input_args["team_id"] == plugin_config.team.pk
    assert input_args["batch_export_id"] == str(batch_export_data["id"])
    assert input_args["interval"] == interval

    # Type specific inputs
    for key, expected in config.items():
        assert input_args[key] == expected


@pytest.mark.django_db
@pytest.mark.parametrize("interval", ("hour", "day"))
@pytest.mark.parametrize(
    "plugin_config",
    (
        ("S3", True),
        ("Snowflake", True),
        ("BigQuery", True),
        ("Redshift", True),
        ("Postgres", True),
        ("Postgres", True, True),
    ),
    indirect=True,
)
@pytest.mark.parametrize("migrate_disabled_plugin_config", (True, False))
def test_create_batch_export_from_app_with_disabled_plugin(
    interval,
    plugin_config,
    migrate_disabled_plugin_config,
):
    """Test a live run of the create_batch_export_from_app command."""
    args = [
        f"--plugin-config-id={plugin_config.id}",
        f"--team-id={plugin_config.team.id}",
        f"--interval={interval}",
    ]
    if migrate_disabled_plugin_config:
        args.append("--migrate-disabled-plugin-config")

    output = call_command("create_batch_export_from_app", *args)

    plugin_config.refresh_from_db()
    assert plugin_config.enabled is False

    export_type, config = map_plugin_config_to_destination(plugin_config)

    batch_export_data = json.loads(output)

    assert batch_export_data["team_id"] == plugin_config.team.id
    assert batch_export_data["interval"] == interval
    assert batch_export_data["name"] == f"{export_type} Export"
    assert batch_export_data["destination_data"] == {
        "type": export_type,
        "config": config,
    }

    if not migrate_disabled_plugin_config:
        assert "id" not in batch_export_data
        return

    assert "id" in batch_export_data

    temporal = sync_connect()

    schedule = describe_schedule(temporal, str(batch_export_data["id"]))
    expected_interval = dt.timedelta(**{f"{interval}s": 1})
    assert schedule.schedule.spec.intervals[0].every == expected_interval

    codec = EncryptionCodec(settings=settings)
    decoded_payload = async_to_sync(codec.decode)(schedule.schedule.action.args)
    input_args = json.loads(decoded_payload[0].data)

    # Common inputs
    assert input_args["team_id"] == plugin_config.team.pk
    assert input_args["batch_export_id"] == str(batch_export_data["id"])
    assert input_args["interval"] == interval

    # Type specific inputs
    for key, expected in config.items():
        assert input_args[key] == expected
