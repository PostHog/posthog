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
from posthog.batch_exports.service import create_batch_export, delete_schedule
from posthog.temporal.client import sync_connect
from posthog.temporal.codec import EncryptionCodec


def test_update_batch_export_fails_with_unknown_batch_export():
    """Test the update_batch_export command fails if BatchExport does not exist."""

    with pytest.raises(CommandError):
        call_command('update_batch_export unknown -p \'{"name": "new-name"}\'')


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
def batch_export(team):
    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": "my-bucket",
            "region": "us-east-1",
            "prefix": "posthog-events/",
            "aws_access_key_id": "object_storage_root_user",
            "aws_secret_access_key": "object_storage_root_password",
        },
    }

    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": "hour",
    }
    batch_export = create_batch_export(
        team_id=team.pk,
        name=batch_export_data["name"],
        destination_data=batch_export_data["destination"],
        interval=batch_export_data["interval"],
    )

    yield batch_export

    temporal = sync_connect()
    delete_schedule(temporal, str(batch_export.pk))

    batch_export.delete()


@pytest.mark.django_db
def test_update_batch_export_fails_with_missing_patch(batch_export):
    """Test the update_batch_export command fails if no patch is provided."""

    with pytest.raises(CommandError):
        call_command(f"update_batch_export {batch_export.id}")


@pytest.mark.django_db
def test_update_batch_export_fails_with_both_patch_and_filename(batch_export):
    """Test the update_batch_export command fails if both patch and filename are provided."""

    with pytest.raises(CommandError):
        call_command("update_batch_export", batch_export.id, '-p {"name": "new-name"}', "-f path/to/my/patch.json")


@pytest.mark.django_db
def test_update_batch_export_dry_run_with_patch(batch_export):
    """Test a dry_run of the update_batch_export command."""

    patch = '-p {"name": "new-name", "interval": "day", "destination": {"type": "Snowflake", "config": {"account": "test-account"}}}'
    result = call_command("update_batch_export", batch_export.id, patch, "--dry-run")
    patched_data = json.loads(result)

    assert patched_data["name"] == "new-name"
    assert patched_data["interval"] == "day"
    assert patched_data["destination_data"]["type"] == "Snowflake"
    assert patched_data["destination_data"]["config"]["account"] == "test-account"


@pytest.mark.django_db
def test_update_batch_export_dry_run_with_filename(batch_export, tmp_path):
    """Test a dry_run of the update_batch_export command."""

    patch_file = tmp_path / "patch.json"
    patch_file.touch()
    patch = {
        "name": "new-name",
        "interval": "day",
        "destination": {"type": "Snowflake", "config": {"account": "test-account"}},
    }
    patch_file.write_text(json.dumps(patch))

    result = call_command("update_batch_export", batch_export.id, f"-f {str(patch_file)}", "--dry-run")
    patched_data = json.loads(result)

    assert patched_data["name"] == "new-name"
    assert patched_data["interval"] == "day"
    assert patched_data["destination_data"]["type"] == "Snowflake"
    assert patched_data["destination_data"]["config"]["account"] == "test-account"


@pytest.mark.django_db
def test_update_batch_export_with_filename(team, batch_export, tmp_path):
    """Test the update_batch_export command."""

    patch_file = tmp_path / "patch.json"
    patch_file.touch()
    patch = {
        "name": "new-name",
        "interval": "day",
        "destination": {
            "config": {
                "bucket_name": "new-bucket-name",
                "region": "eu-central-1",
                "prefix": "new-events/",
                "aws_access_key_id": "new-access-key",
                "aws_secret_access_key": "new-secret",
            }
        },
    }
    patch_file.write_text(json.dumps(patch))

    result = call_command("update_batch_export", batch_export.id, f"-f {str(patch_file)}")
    patched_data = json.loads(result)

    assert patched_data["name"] == "new-name"
    assert patched_data["interval"] == "day"
    assert patched_data["destination_data"]["config"]["bucket_name"] == "new-bucket-name"

    temporal = sync_connect()

    schedule = describe_schedule(temporal, str(batch_export.id))
    expected_interval = dt.timedelta(days=1)
    assert schedule.schedule.spec.intervals[0].every == expected_interval

    codec = EncryptionCodec(settings=settings)
    decoded_payload = async_to_sync(codec.decode)(schedule.schedule.action.args)
    args = json.loads(decoded_payload[0].data)

    # Common inputs
    assert args["team_id"] == team.pk
    assert args["batch_export_id"] == str(batch_export.id)
    assert args["interval"] == "day"

    # S3 specific inputs
    assert args["bucket_name"] == "new-bucket-name"
    assert args["region"] == "eu-central-1"
    assert args["prefix"] == "new-events/"
    assert args["aws_access_key_id"] == "new-access-key"
    assert args["aws_secret_access_key"] == "new-secret"


@pytest.mark.django_db
def test_update_batch_export_with_patch(team, batch_export):
    """Test the update_batch_export command."""

    patch = {
        "name": "new-name",
        "interval": "day",
        "destination": {
            "config": {
                "bucket_name": "new-bucket-name",
                "region": "eu-central-1",
                "prefix": "new-events/",
                "aws_access_key_id": "new-access-key",
                "aws_secret_access_key": "new-secret",
            }
        },
    }
    result = call_command("update_batch_export", batch_export.id, f"-p {json.dumps(patch)}")
    patched_data = json.loads(result)

    assert patched_data["name"] == "new-name"
    assert patched_data["interval"] == "day"
    assert patched_data["destination_data"]["config"]["bucket_name"] == "new-bucket-name"

    temporal = sync_connect()

    schedule = describe_schedule(temporal, str(batch_export.id))
    expected_interval = dt.timedelta(days=1)
    assert schedule.schedule.spec.intervals[0].every == expected_interval

    codec = EncryptionCodec(settings=settings)
    decoded_payload = async_to_sync(codec.decode)(schedule.schedule.action.args)
    args = json.loads(decoded_payload[0].data)

    # Common inputs
    assert args["team_id"] == team.pk
    assert args["batch_export_id"] == str(batch_export.id)
    assert args["interval"] == "day"

    # S3 specific inputs
    assert args["bucket_name"] == "new-bucket-name"
    assert args["region"] == "eu-central-1"
    assert args["prefix"] == "new-events/"
    assert args["aws_access_key_id"] == "new-access-key"
    assert args["aws_secret_access_key"] == "new-secret"
