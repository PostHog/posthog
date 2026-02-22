import datetime
from io import StringIO

import pytest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError

from botocore.exceptions import ClientError
from parameterized import parameterized

RECOVERY_ARN = "arn:aws:backup:us-east-1:123456789012:recovery-point:abc123"
ROLE_ARN = "arn:aws:iam::123456789012:role/backup-role"
RESTORE_JOB_ID = "restore-job-001"
RESTORED_TABLE = "session-recording-keys-restore-1234567890"

ITEM_ENCRYPTED = {
    "session_id": {"S": "session-abc"},
    "team_id": {"N": "42"},
    "session_state": {"S": "encrypted"},
}

ITEM_CLEARTEXT = {
    "session_id": {"S": "session-xyz"},
    "team_id": {"N": "42"},
    "session_state": {"S": "cleartext"},
}

ITEM_DELETED = {
    "session_id": {"S": "session-del"},
    "team_id": {"N": "42"},
    "session_state": {"S": "deleted"},
}


def _make_client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "Operation")


def _make_backup_client(
    *,
    recovery_point_arn: str = RECOVERY_ARN,
    role_arn: str = ROLE_ARN,
    restore_job_id: str = RESTORE_JOB_ID,
    restore_status: str = "COMPLETED",
    recovery_points: list[dict] | None = None,
) -> MagicMock:
    if recovery_points is None:
        recovery_points = [
            {
                "RecoveryPointArn": recovery_point_arn,
                "Status": "COMPLETED",
                "CompletionDate": datetime.datetime(2024, 6, 1, 12, 0, 0),
            }
        ]

    paginator = MagicMock()
    paginator.paginate.return_value = [{"RecoveryPoints": recovery_points}]

    client = MagicMock()
    client.get_paginator.return_value = paginator
    client.list_backup_plans.return_value = {"BackupPlansList": [{"BackupPlanId": "plan-1"}]}
    client.list_backup_selections.return_value = {"BackupSelectionsList": [{"SelectionId": "sel-1"}]}
    client.get_backup_selection.return_value = {
        "BackupSelection": {
            "IamRoleArn": role_arn,
            "Resources": ["arn:aws:dynamodb:us-east-1:123:table/session-recording-keys"],
        }
    }
    client.start_restore_job.return_value = {"RestoreJobId": restore_job_id}
    client.describe_restore_job.return_value = {"Status": restore_status}
    return client


def _make_dynamodb_client(
    *,
    get_item_response: dict | None = None,
    query_items: list[dict] | None = None,
) -> MagicMock:
    client = MagicMock()

    if get_item_response is not None:
        client.get_item.return_value = get_item_response
    else:
        client.get_item.return_value = {"Item": ITEM_ENCRYPTED}

    if query_items is not None:
        client.query.return_value = {"Items": query_items}
    else:
        client.query.return_value = {"Items": [ITEM_ENCRYPTED]}

    client.put_item.return_value = {}
    client.delete_table.return_value = {}
    return client


def _patch_clients(backup_client: MagicMock, dynamodb_client: MagicMock):
    def side_effect(service_name):
        if service_name == "backup":
            return backup_client
        if service_name == "dynamodb":
            return dynamodb_client
        raise ValueError(f"Unexpected boto3.client call: {service_name}")

    return patch(
        "posthog.management.commands.restore_session_recording_keys.boto3.client",
        side_effect=side_effect,
    )


class TestRestoreSessionRecordingKeysCommand:
    def test_single_key_restore_writes_to_live_table(self):
        backup = _make_backup_client(recovery_point_arn=RECOVERY_ARN)
        dynamodb = _make_dynamodb_client(get_item_response={"Item": ITEM_ENCRYPTED})

        out = StringIO()
        with _patch_clients(backup, dynamodb):
            call_command(
                "restore_session_recording_keys",
                "--team-id=42",
                "--session-id=session-abc",
                "--recovery-point-arn=" + RECOVERY_ARN,
                stdout=out,
            )

        dynamodb.put_item.assert_called_once_with(
            TableName="session-recording-keys",
            Item=ITEM_ENCRYPTED,
            ConditionExpression="session_state = :deleted OR attribute_not_exists(session_id)",
            ExpressionAttributeValues={":deleted": {"S": "deleted"}},
        )

    def test_team_wide_restore_writes_all_non_deleted_keys(self):
        backup = _make_backup_client(recovery_point_arn=RECOVERY_ARN)
        dynamodb = _make_dynamodb_client(
            query_items=[ITEM_ENCRYPTED, ITEM_CLEARTEXT],
        )

        out = StringIO()
        with _patch_clients(backup, dynamodb):
            call_command(
                "restore_session_recording_keys",
                "--team-id=42",
                "--recovery-point-arn=" + RECOVERY_ARN,
                stdout=out,
            )

        assert dynamodb.put_item.call_count == 2
        written_items = [c.kwargs["Item"] for c in dynamodb.put_item.call_args_list]
        assert ITEM_ENCRYPTED in written_items
        assert ITEM_CLEARTEXT in written_items

    def test_dry_run_does_not_write_to_live_table(self):
        backup = _make_backup_client(recovery_point_arn=RECOVERY_ARN)
        dynamodb = _make_dynamodb_client(get_item_response={"Item": ITEM_ENCRYPTED})

        out = StringIO()
        with _patch_clients(backup, dynamodb):
            call_command(
                "restore_session_recording_keys",
                "--team-id=42",
                "--session-id=session-abc",
                "--recovery-point-arn=" + RECOVERY_ARN,
                "--dry-run",
                stdout=out,
            )

        dynamodb.put_item.assert_not_called()
        assert "DRY RUN" in out.getvalue()

    def test_dry_run_reports_what_would_be_restored(self):
        backup = _make_backup_client(recovery_point_arn=RECOVERY_ARN)
        dynamodb = _make_dynamodb_client(query_items=[ITEM_ENCRYPTED, ITEM_CLEARTEXT])

        out = StringIO()
        with _patch_clients(backup, dynamodb):
            call_command(
                "restore_session_recording_keys",
                "--team-id=42",
                "--recovery-point-arn=" + RECOVERY_ARN,
                "--dry-run",
                stdout=out,
            )

        output = out.getvalue()
        assert "session-abc" in output
        assert "session-xyz" in output
        assert dynamodb.put_item.call_count == 0

    def test_skips_item_already_active_in_live_table(self):
        backup = _make_backup_client(recovery_point_arn=RECOVERY_ARN)
        dynamodb = _make_dynamodb_client(get_item_response={"Item": ITEM_ENCRYPTED})
        dynamodb.put_item.side_effect = _make_client_error("ConditionalCheckFailedException")

        out = StringIO()
        with _patch_clients(backup, dynamodb):
            call_command(
                "restore_session_recording_keys",
                "--team-id=42",
                "--session-id=session-abc",
                "--recovery-point-arn=" + RECOVERY_ARN,
                stdout=out,
            )

        output = out.getvalue()
        assert "Skipped" in output
        assert "session-abc" in output

    def test_other_dynamodb_errors_are_re_raised(self):
        backup = _make_backup_client(recovery_point_arn=RECOVERY_ARN)
        dynamodb = _make_dynamodb_client(get_item_response={"Item": ITEM_ENCRYPTED})
        dynamodb.put_item.side_effect = _make_client_error("ProvisionedThroughputExceededException")

        with _patch_clients(backup, dynamodb):
            with pytest.raises(ClientError):
                call_command(
                    "restore_session_recording_keys",
                    "--team-id=42",
                    "--session-id=session-abc",
                    "--recovery-point-arn=" + RECOVERY_ARN,
                )

    def test_skips_single_key_that_is_deleted_in_backup(self):
        backup = _make_backup_client(recovery_point_arn=RECOVERY_ARN)
        dynamodb = _make_dynamodb_client(get_item_response={"Item": ITEM_DELETED})

        out = StringIO()
        with _patch_clients(backup, dynamodb):
            call_command(
                "restore_session_recording_keys",
                "--team-id=42",
                "--session-id=session-del",
                "--recovery-point-arn=" + RECOVERY_ARN,
                stdout=out,
            )

        dynamodb.put_item.assert_not_called()
        output = out.getvalue()
        assert "deleted in backup" in output

    def test_single_key_not_found_in_backup_writes_nothing(self):
        backup = _make_backup_client(recovery_point_arn=RECOVERY_ARN)
        dynamodb = _make_dynamodb_client(get_item_response={})

        out = StringIO()
        with _patch_clients(backup, dynamodb):
            call_command(
                "restore_session_recording_keys",
                "--team-id=42",
                "--session-id=session-missing",
                "--recovery-point-arn=" + RECOVERY_ARN,
                stdout=out,
            )

        dynamodb.put_item.assert_not_called()
        assert "not found in backup" in out.getvalue()

    def test_uses_latest_recovery_point_when_no_arn_specified(self):
        older = {
            "RecoveryPointArn": "arn:aws:backup:::older",
            "Status": "COMPLETED",
            "CompletionDate": datetime.datetime(2024, 5, 1, 0, 0, 0),
        }
        newer = {
            "RecoveryPointArn": "arn:aws:backup:::newer",
            "Status": "COMPLETED",
            "CompletionDate": datetime.datetime(2024, 6, 1, 12, 0, 0),
        }
        backup = _make_backup_client(recovery_points=[older, newer])
        backup.start_restore_job.return_value = {"RestoreJobId": RESTORE_JOB_ID}
        dynamodb = _make_dynamodb_client(get_item_response={"Item": ITEM_ENCRYPTED})

        out = StringIO()
        with _patch_clients(backup, dynamodb):
            call_command(
                "restore_session_recording_keys",
                "--team-id=42",
                "--session-id=session-abc",
                stdout=out,
            )

        _, kwargs = backup.start_restore_job.call_args
        assert kwargs["RecoveryPointArn"] == "arn:aws:backup:::newer"

    def test_uses_specified_recovery_point_arn_directly(self):
        explicit_arn = "arn:aws:backup:::explicit"
        backup = _make_backup_client(recovery_point_arn=explicit_arn)
        dynamodb = _make_dynamodb_client(get_item_response={"Item": ITEM_ENCRYPTED})

        out = StringIO()
        with _patch_clients(backup, dynamodb):
            call_command(
                "restore_session_recording_keys",
                "--team-id=42",
                "--session-id=session-abc",
                f"--recovery-point-arn={explicit_arn}",
                stdout=out,
            )

        backup.get_paginator.assert_not_called()
        _, kwargs = backup.start_restore_job.call_args
        assert kwargs["RecoveryPointArn"] == explicit_arn

    def test_raises_when_no_completed_recovery_points(self):
        backup = _make_backup_client(recovery_points=[])
        dynamodb = _make_dynamodb_client()

        with _patch_clients(backup, dynamodb):
            with pytest.raises(CommandError, match="No completed recovery points"):
                call_command(
                    "restore_session_recording_keys",
                    "--team-id=42",
                    "--session-id=session-abc",
                )

    def test_raises_when_only_non_completed_recovery_points_exist(self):
        incomplete = [
            {
                "RecoveryPointArn": RECOVERY_ARN,
                "Status": "PARTIAL",
                "CompletionDate": datetime.datetime(2024, 6, 1, 0, 0, 0),
            }
        ]
        backup = _make_backup_client(recovery_points=incomplete)
        dynamodb = _make_dynamodb_client()

        with _patch_clients(backup, dynamodb):
            with pytest.raises(CommandError, match="No completed recovery points"):
                call_command(
                    "restore_session_recording_keys",
                    "--team-id=42",
                    "--session-id=session-abc",
                )

    @parameterized.expand(
        [
            ("aborted", "ABORTED", "ABORTED"),
            ("failed", "FAILED", "FAILED"),
        ]
    )
    def test_raises_when_restore_job_terminates_with_error(self, _name, job_status, expected_in_message):
        backup = _make_backup_client(recovery_point_arn=RECOVERY_ARN, restore_status=job_status)
        backup.describe_restore_job.return_value = {
            "Status": job_status,
            "StatusMessage": f"job {job_status.lower()}",
        }
        dynamodb = _make_dynamodb_client()

        with _patch_clients(backup, dynamodb):
            with pytest.raises(CommandError, match=expected_in_message):
                call_command(
                    "restore_session_recording_keys",
                    "--team-id=42",
                    "--session-id=session-abc",
                    "--recovery-point-arn=" + RECOVERY_ARN,
                )

    def test_restore_timeout_raises_command_error(self):
        backup = _make_backup_client(recovery_point_arn=RECOVERY_ARN)
        backup.describe_restore_job.return_value = {"Status": "RUNNING"}
        dynamodb = _make_dynamodb_client()

        with _patch_clients(backup, dynamodb):
            with (
                patch("posthog.management.commands.restore_session_recording_keys.time.time") as mock_time,
                patch("posthog.management.commands.restore_session_recording_keys.time.sleep"),
            ):
                mock_time.side_effect = [
                    0.0,  # start_time in handle (restored_table_name)
                    0.0,  # start_time in _wait_for_restore
                    0.0,  # first elapsed check
                    99999.0,  # second check — exceeds timeout
                ]
                with pytest.raises(CommandError, match="Restore timed out"):
                    call_command(
                        "restore_session_recording_keys",
                        "--team-id=42",
                        "--session-id=session-abc",
                        "--recovery-point-arn=" + RECOVERY_ARN,
                    )

    def test_cleanup_deletes_restored_table(self):
        backup = _make_backup_client(recovery_point_arn=RECOVERY_ARN)
        dynamodb = _make_dynamodb_client(get_item_response={"Item": ITEM_ENCRYPTED})

        with _patch_clients(backup, dynamodb):
            call_command(
                "restore_session_recording_keys",
                "--team-id=42",
                "--session-id=session-abc",
                "--recovery-point-arn=" + RECOVERY_ARN,
            )

        dynamodb.delete_table.assert_called_once()

    def test_skip_cleanup_does_not_delete_restored_table(self):
        backup = _make_backup_client(recovery_point_arn=RECOVERY_ARN)
        dynamodb = _make_dynamodb_client(get_item_response={"Item": ITEM_ENCRYPTED})

        out = StringIO()
        with _patch_clients(backup, dynamodb):
            call_command(
                "restore_session_recording_keys",
                "--team-id=42",
                "--session-id=session-abc",
                "--recovery-point-arn=" + RECOVERY_ARN,
                "--skip-cleanup",
                stdout=out,
            )

        dynamodb.delete_table.assert_not_called()
        assert "Skipping cleanup" in out.getvalue()

    def test_cleanup_runs_even_when_restore_items_fails(self):
        backup = _make_backup_client(recovery_point_arn=RECOVERY_ARN)
        dynamodb = _make_dynamodb_client(get_item_response={"Item": ITEM_ENCRYPTED})
        dynamodb.put_item.side_effect = _make_client_error("InternalServerError")

        with _patch_clients(backup, dynamodb):
            with pytest.raises(ClientError):
                call_command(
                    "restore_session_recording_keys",
                    "--team-id=42",
                    "--session-id=session-abc",
                    "--recovery-point-arn=" + RECOVERY_ARN,
                )

        dynamodb.delete_table.assert_called_once()

    def test_cleanup_failure_is_tolerated(self):
        backup = _make_backup_client(recovery_point_arn=RECOVERY_ARN)
        dynamodb = _make_dynamodb_client(get_item_response={"Item": ITEM_ENCRYPTED})
        dynamodb.delete_table.side_effect = _make_client_error("ResourceNotFoundException")

        out = StringIO()
        with _patch_clients(backup, dynamodb):
            call_command(
                "restore_session_recording_keys",
                "--team-id=42",
                "--session-id=session-abc",
                "--recovery-point-arn=" + RECOVERY_ARN,
                stdout=out,
            )

        assert "Failed to delete restored table" in out.getvalue()

    def test_team_wide_restore_uses_gsi_query_not_get_item(self):
        backup = _make_backup_client(recovery_point_arn=RECOVERY_ARN)
        dynamodb = _make_dynamodb_client(query_items=[ITEM_ENCRYPTED])

        with _patch_clients(backup, dynamodb):
            call_command(
                "restore_session_recording_keys",
                "--team-id=42",
                "--recovery-point-arn=" + RECOVERY_ARN,
            )

        dynamodb.get_item.assert_not_called()
        dynamodb.query.assert_called_once()
        query_kwargs = dynamodb.query.call_args.kwargs
        assert query_kwargs["IndexName"] == "team_id-index"
        assert ":deleted" in query_kwargs["ExpressionAttributeValues"]

    def test_team_wide_restore_paginates_through_all_results(self):
        backup = _make_backup_client(recovery_point_arn=RECOVERY_ARN)
        dynamodb = _make_dynamodb_client()

        page1 = {"Items": [ITEM_ENCRYPTED], "LastEvaluatedKey": {"session_id": {"S": "session-abc"}}}
        page2 = {"Items": [ITEM_CLEARTEXT]}
        dynamodb.query.side_effect = [page1, page2]

        with _patch_clients(backup, dynamodb):
            call_command(
                "restore_session_recording_keys",
                "--team-id=42",
                "--recovery-point-arn=" + RECOVERY_ARN,
            )

        assert dynamodb.query.call_count == 2
        assert dynamodb.put_item.call_count == 2

    def test_team_wide_restore_with_no_items_reports_nothing_to_restore(self):
        backup = _make_backup_client(recovery_point_arn=RECOVERY_ARN)
        dynamodb = _make_dynamodb_client(query_items=[])

        out = StringIO()
        with _patch_clients(backup, dynamodb):
            call_command(
                "restore_session_recording_keys",
                "--team-id=42",
                "--recovery-point-arn=" + RECOVERY_ARN,
                stdout=out,
            )

        dynamodb.put_item.assert_not_called()
        assert "Nothing to restore" in out.getvalue()

    def test_mixed_restore_skipped_and_written_are_counted(self):
        item_active = {
            "session_id": {"S": "session-active"},
            "team_id": {"N": "42"},
            "session_state": {"S": "encrypted"},
        }
        item_deleted = {
            "session_id": {"S": "session-was-deleted"},
            "team_id": {"N": "42"},
            "session_state": {"S": "encrypted"},
        }

        backup = _make_backup_client(recovery_point_arn=RECOVERY_ARN)
        dynamodb = _make_dynamodb_client(query_items=[item_active, item_deleted])

        def conditional_put(**kwargs):
            if kwargs["Item"]["session_id"]["S"] == "session-active":
                raise _make_client_error("ConditionalCheckFailedException")
            return {}

        dynamodb.put_item.side_effect = conditional_put

        out = StringIO()
        with _patch_clients(backup, dynamodb):
            call_command(
                "restore_session_recording_keys",
                "--team-id=42",
                "--recovery-point-arn=" + RECOVERY_ARN,
                stdout=out,
            )

        output = out.getvalue()
        assert "1 restored" in output
        assert "1 skipped" in output

    def test_raises_when_no_iam_role_found_for_backup(self):
        backup = _make_backup_client(recovery_point_arn=RECOVERY_ARN)
        backup.get_backup_selection.return_value = {
            "BackupSelection": {
                "IamRoleArn": "arn:aws:iam:::role/other-role",
                "Resources": ["arn:aws:dynamodb:us-east-1:123:table/some-other-table"],
            }
        }
        dynamodb = _make_dynamodb_client()

        with _patch_clients(backup, dynamodb):
            with pytest.raises(CommandError, match="Could not find IAM role"):
                call_command(
                    "restore_session_recording_keys",
                    "--team-id=42",
                    "--session-id=session-abc",
                    "--recovery-point-arn=" + RECOVERY_ARN,
                )

    def test_single_key_query_passes_correct_key_to_get_item(self):
        backup = _make_backup_client(recovery_point_arn=RECOVERY_ARN)
        dynamodb = _make_dynamodb_client(get_item_response={"Item": ITEM_ENCRYPTED})

        with _patch_clients(backup, dynamodb):
            call_command(
                "restore_session_recording_keys",
                "--team-id=42",
                "--session-id=session-abc",
                "--recovery-point-arn=" + RECOVERY_ARN,
            )

        get_item_call = dynamodb.get_item.call_args
        key = get_item_call.kwargs["Key"]
        assert key["session_id"] == {"S": "session-abc"}
        assert key["team_id"] == {"N": "42"}
