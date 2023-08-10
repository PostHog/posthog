import datetime as dt
import json

import pytest
from asgiref.sync import async_to_sync
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

from posthog.api.test.batch_exports.conftest import describe_schedule
from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
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
def snowflake_plugin(organization):
    plugin = Plugin.objects.create(
        name="Snowflake Export",
        url="https://github.com/PostHog/snowflake-export-plugin",
        plugin_type="custom",
        organization=organization,
    )
    yield plugin
    plugin.delete()


test_config = {
    "account": "snowflake-account",
    "username": "test-user",
    "password": "test-password",
    "warehouse": "test-warehouse",
    "database": "test-db",
    "dbschema": "test-schema",
    "table": "test-table",
    "role": "test-role",
}


@pytest.fixture
def snowflake_plugin_config(snowflake_plugin, team):
    plugin_config = PluginConfig.objects.create(
        plugin=snowflake_plugin, order=1, team=team, enabled=True, config=test_config
    )
    yield plugin_config
    plugin_config.delete()


@pytest.mark.django_db
def test_create_batch_export_from_app_fails_with_mismatched_team_id(snowflake_plugin_config):
    """Test the create_batch_export_from_app command fails if team_id does not match PluginConfig.team_id."""

    with pytest.raises(CommandError):
        call_command(
            "create_batch_export_from_app",
            "--name='Snowflake BatchExport'",
            f"--plugin-config-id={snowflake_plugin_config.id}",
            "--team-id=0",
        )


@pytest.mark.django_db
def test_create_batch_export_from_app_dry_run(snowflake_plugin_config, team):
    """Test a dry_run of the create_batch_export_from_app command."""

    output = call_command(
        "create_batch_export_from_app",
        f"--plugin-config-id={snowflake_plugin_config.id}",
        f"--team-id={team.id}",
        "--dry-run",
    )
    batch_export_data = json.loads(output)

    assert batch_export_data["team_id"] == team.id
    assert batch_export_data["interval"] == "hour"
    assert batch_export_data["name"] == "Snowflake Export"
    assert batch_export_data["destination_data"] == {
        "type": "Snowflake",
        "config": {
            "account": test_config["account"],
            "database": test_config["database"],
            "warehouse": test_config["warehouse"],
            "user": test_config["username"],
            "password": test_config["password"],
            "schema": test_config["dbschema"],
            "table_name": test_config["table"],
            "role": test_config["role"],
        },
    }


@pytest.mark.django_db
@pytest.mark.parametrize("interval", ["hour", "day"])
def test_create_batch_export_from_app(snowflake_plugin_config, team, interval):
    """Test a dry_run of the create_batch_export_from_app command."""

    output = call_command(
        "create_batch_export_from_app",
        f"--plugin-config-id={snowflake_plugin_config.id}",
        f"--team-id={team.id}",
        f"--interval={interval}",
    )
    batch_export_data = json.loads(output)

    assert batch_export_data["team_id"] == team.id
    assert batch_export_data["interval"] == interval
    assert batch_export_data["name"] == "Snowflake Export"
    assert batch_export_data["destination_data"] == {
        "type": "Snowflake",
        "config": {
            "account": test_config["account"],
            "database": test_config["database"],
            "warehouse": test_config["warehouse"],
            "user": test_config["username"],
            "password": test_config["password"],
            "schema": test_config["dbschema"],
            "table_name": test_config["table"],
            "role": test_config["role"],
        },
    }

    temporal = sync_connect()

    schedule = describe_schedule(temporal, str(batch_export_data["id"]))
    expected_interval = dt.timedelta(**{f"{interval}s": 1})
    assert schedule.schedule.spec.intervals[0].every == expected_interval

    codec = EncryptionCodec(settings=settings)
    decoded_payload = async_to_sync(codec.decode)(schedule.schedule.action.args)
    args = json.loads(decoded_payload[0].data)

    # Common inputs
    assert args["team_id"] == team.pk
    assert args["batch_export_id"] == str(batch_export_data["id"])
    assert args["interval"] == interval

    # Snowflake specific inputs
    assert args["account"] == test_config["account"]
    assert args["database"] == test_config["database"]
    assert args["warehouse"] == test_config["warehouse"]
    assert args["user"] == test_config["username"]
    assert args["password"] == test_config["password"]
    assert args["schema"] == test_config["dbschema"]
    assert args["table_name"] == test_config["table"]
    assert args["role"] == test_config["role"]
