import datetime as dt
import itertools
import json
import typing

import pytest
from asgiref.sync import async_to_sync
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

from posthog.api.test.batch_exports.conftest import describe_schedule, start_test_worker
from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.management.commands.create_batch_export_from_app import (
    map_plugin_config_to_destination,
)
from posthog.models import Plugin, PluginConfig
from posthog.temporal.client import sync_connect
from posthog.temporal.codec import EncryptionCodec


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


@pytest.fixture
def snowflake_plugin(organization) -> typing.Generator[Plugin, None, None]:
    plugin = Plugin.objects.create(
        name="Snowflake Export",
        url="https://github.com/PostHog/snowflake-export-plugin",
        plugin_type="custom",
        organization=organization,
    )
    yield plugin
    plugin.delete()


@pytest.fixture
def s3_plugin(organization) -> typing.Generator[Plugin, None, None]:
    plugin = Plugin.objects.create(
        name="S3 Export Plugin",
        url="https://github.com/PostHog/s3-export-plugin",
        plugin_type="custom",
        organization=organization,
    )
    yield plugin
    plugin.delete()


test_snowflake_config = {
    "account": "snowflake-account",
    "username": "test-user",
    "password": "test-password",
    "warehouse": "test-warehouse",
    "database": "test-db",
    "dbschema": "test-schema",
    "table": "test-table",
    "role": "test-role",
}
test_s3_config = {
    "awsAccessKey": "access-key",
    "awsSecretAccessKey": "secret-access-key",
    "s3BucketName": "test-bucket",
    "awsRegion": "eu-central-1",
    "prefix": "posthog/",
    "compression": "gzip",
    "eventsToIgnore": "$feature_flag_called",
}


@pytest.fixture
def config(request):
    if request.param == "S3":
        return test_s3_config
    elif request.param == "Snowflake":
        return test_snowflake_config
    else:
        raise ValueError(f"Unsupported plugin: {request.param}")


@pytest.fixture
def snowflake_plugin_config(snowflake_plugin, team) -> typing.Generator[PluginConfig, None, None]:
    plugin_config = PluginConfig.objects.create(
        plugin=snowflake_plugin, order=1, team=team, enabled=True, config=test_snowflake_config
    )
    yield plugin_config
    plugin_config.delete()


@pytest.fixture
def s3_plugin_config(s3_plugin, team) -> typing.Generator[PluginConfig, None, None]:
    plugin_config = PluginConfig.objects.create(
        plugin=s3_plugin, order=1, team=team, enabled=True, config=test_s3_config
    )
    yield plugin_config
    plugin_config.delete()


@pytest.fixture
def plugin_config(request, s3_plugin_config, snowflake_plugin_config) -> PluginConfig:
    if request.param == "S3":
        return s3_plugin_config
    elif request.param == "Snowflake":
        return snowflake_plugin_config
    else:
        raise ValueError(f"Unsupported plugin: {request.param}")


@pytest.fixture
def disabled_plugin_config(request, s3_plugin_config, snowflake_plugin_config) -> PluginConfig:
    if request.param == "S3":
        s3_plugin_config.enabled = False
        s3_plugin_config.save()
        return s3_plugin_config
    elif request.param == "Snowflake":
        snowflake_plugin_config.enabled = False
        snowflake_plugin_config.save()
        return snowflake_plugin_config
    else:
        raise ValueError(f"Unsupported plugin: {request.param}")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "plugin_config,config,expected_type",
    [("S3", "S3", "S3"), ("Snowflake", "Snowflake", "Snowflake")],
    indirect=["plugin_config", "config"],
)
def test_map_plugin_config_to_destination(plugin_config, config, expected_type):
    """Test we are mapping PluginConfig to the correct destination type and values."""
    export_type, export_config = map_plugin_config_to_destination(plugin_config)

    assert export_type == expected_type

    result_values = list(export_config.values())
    for key, value in config.items():
        if key == "eventsToIgnore":
            assert value in export_config["exclude_events"]
            continue

        assert value in result_values


@pytest.mark.django_db
@pytest.mark.parametrize("plugin_config", ["S3", "Snowflake"], indirect=True)
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
@pytest.mark.parametrize("plugin_config", ["S3", "Snowflake"], indirect=True)
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
@pytest.mark.parametrize(
    "interval,plugin_config,disable_plugin_config",
    itertools.product(["hour", "day"], ["S3", "Snowflake"], [True, False]),
    indirect=["plugin_config"],
)
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
    args = json.loads(decoded_payload[0].data)

    # Common inputs
    assert args["team_id"] == plugin_config.team.pk
    assert args["batch_export_id"] == str(batch_export_data["id"])
    assert args["interval"] == interval

    # Type specific inputs
    for key, expected in config.items():
        assert args[key] == expected


@pytest.mark.django_db
@pytest.mark.parametrize(
    "interval,disabled_plugin_config,migrate_disabled_plugin_config",
    itertools.product(["hour", "day"], ["S3", "Snowflake"], [True, False]),
    indirect=["disabled_plugin_config"],
)
def test_create_batch_export_from_app_with_disabled_plugin(
    interval,
    disabled_plugin_config,
    migrate_disabled_plugin_config,
):
    """Test a live run of the create_batch_export_from_app command."""
    args = [
        f"--plugin-config-id={disabled_plugin_config.id}",
        f"--team-id={disabled_plugin_config.team.id}",
        f"--interval={interval}",
    ]
    if migrate_disabled_plugin_config:
        args.append("--migrate-disabled-plugin-config")

    output = call_command("create_batch_export_from_app", *args)

    disabled_plugin_config.refresh_from_db()
    assert disabled_plugin_config.enabled is False

    export_type, config = map_plugin_config_to_destination(disabled_plugin_config)

    batch_export_data = json.loads(output)

    assert batch_export_data["team_id"] == disabled_plugin_config.team.id
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
    args = json.loads(decoded_payload[0].data)

    # Common inputs
    assert args["team_id"] == disabled_plugin_config.team.pk
    assert args["batch_export_id"] == str(batch_export_data["id"])
    assert args["interval"] == interval

    # Type specific inputs
    for key, expected in config.items():
        assert args[key] == expected


@async_to_sync
async def list_workflows(temporal, schedule_id: str):
    """List Workflows scheduled by given Schedule."""
    workflows = []

    while len(workflows) == 0:
        workflows = [workflow async for workflow in temporal.list_workflows(f'TemporalScheduledById="{schedule_id}"')]

    return workflows


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "interval,plugin_config",
    [
        ("hour", "S3"),
        ("day", "S3"),
        ("hour", "Snowflake"),
        ("day", "Snowflake"),
    ],
    indirect=["plugin_config"],
)
def test_create_batch_export_from_app_with_backfill(interval, plugin_config):
    """Test a live run of the create_batch_export_from_app command with the backfill flag set."""
    args = (
        f"--plugin-config-id={plugin_config.id}",
        f"--team-id={plugin_config.team.id}",
        f"--interval={interval}",
        "--backfill-batch-export",
    )
    export_type, _ = map_plugin_config_to_destination(plugin_config)

    temporal = sync_connect()

    with start_test_worker(temporal):
        output = call_command("create_batch_export_from_app", *args)

        batch_export_data = json.loads(output)
        # time.sleep(10)
        workflows = list_workflows(temporal, str(batch_export_data["id"]))

        assert len(workflows) == 1
        workflow_execution = workflows[0]
        assert workflow_execution.workflow_type == f"{export_type.lower()}-export"
