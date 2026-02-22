import json
import time

from django.core.management.base import BaseCommand, CommandError

import boto3
from botocore.exceptions import ClientError

from posthog.clickhouse.client import sync_execute
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.settings.data_stores import CLICKHOUSE_CLUSTER

LIVE_TABLE_NAME = "session-recording-keys"
BACKUP_VAULT_NAME = "session-recording-keys-vault"
TEAM_ID_INDEX = "team_id-index"
RESTORE_POLL_INTERVAL_SECONDS = 30
RESTORE_TIMEOUT_SECONDS = 30 * 60


class Command(BaseCommand):
    help = "Restore session recording encryption keys from AWS Backup"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True, help="Team ID to restore keys for")
        parser.add_argument("--session-id", type=str, help="Restore a single key (omit to restore all keys for team)")
        parser.add_argument("--recovery-point-arn", type=str, help="Use a specific recovery point (default: latest)")
        parser.add_argument("--skip-cleanup", action="store_true", help="Keep the restored table for further queries")
        parser.add_argument("--dry-run", action="store_true", help="Show what would be restored without writing")

    def handle(self, *args, **options):
        team_id: int = options["team_id"]
        session_id: str | None = options["session_id"]
        recovery_point_arn: str | None = options["recovery_point_arn"]
        skip_cleanup: bool = options["skip_cleanup"]
        dry_run: bool = options["dry_run"]

        backup_client = boto3.client("backup")
        dynamodb_client = boto3.client("dynamodb")

        # Step 1: Find recovery point
        recovery_point_arn = self._resolve_recovery_point(backup_client, recovery_point_arn)

        # Step 2: Start restore job
        restored_table_name = f"session-recording-keys-restore-{int(time.time())}"
        iam_role_arn = self._get_backup_iam_role(backup_client)
        restore_job_id = self._start_restore(backup_client, recovery_point_arn, restored_table_name, iam_role_arn)

        try:
            # Step 3: Wait for restore
            self._wait_for_restore(backup_client, restore_job_id)

            # Step 4: Query restored table
            items = self._query_restored_table(dynamodb_client, restored_table_name, team_id, session_id)

            # Step 5: Write to live table
            self._restore_items(dynamodb_client, items, dry_run)
        finally:
            # Step 6: Cleanup
            if not skip_cleanup:
                self._cleanup(dynamodb_client, restored_table_name)
            else:
                self.stdout.write(f"Skipping cleanup — restored table: {restored_table_name}")

    def _resolve_recovery_point(self, backup_client, recovery_point_arn: str | None) -> str:
        if recovery_point_arn:
            self.stdout.write(f"Using specified recovery point: {recovery_point_arn}")
            return recovery_point_arn

        self.stdout.write(f"Listing recovery points in vault: {BACKUP_VAULT_NAME}")

        paginator = backup_client.get_paginator("list_recovery_points_by_backup_vault")
        recovery_points = []
        for page in paginator.paginate(BackupVaultName=BACKUP_VAULT_NAME):
            recovery_points.extend(page.get("RecoveryPoints", []))

        completed = [rp for rp in recovery_points if rp.get("Status") == "COMPLETED"]
        if not completed:
            raise CommandError(f"No completed recovery points found in vault {BACKUP_VAULT_NAME}")

        completed.sort(key=lambda rp: rp["CompletionDate"], reverse=True)
        latest = completed[0]
        arn = latest["RecoveryPointArn"]
        completion_date = latest["CompletionDate"].isoformat()

        self.stdout.write(self.style.SUCCESS(f"Using latest recovery point: {arn} (completed {completion_date})"))
        return arn

    def _get_backup_iam_role(self, backup_client) -> str:
        plans = backup_client.list_backup_plans().get("BackupPlansList", [])

        for plan in plans:
            selections = backup_client.list_backup_selections(BackupPlanId=plan["BackupPlanId"]).get(
                "BackupSelectionsList", []
            )
            for selection in selections:
                detail = backup_client.get_backup_selection(
                    BackupPlanId=plan["BackupPlanId"],
                    SelectionId=selection["SelectionId"],
                )
                iam_role_arn = detail["BackupSelection"].get("IamRoleArn", "")
                resources = detail["BackupSelection"].get("Resources", [])
                if any(LIVE_TABLE_NAME in r for r in resources):
                    self.stdout.write(f"Found IAM role: {iam_role_arn}")
                    return iam_role_arn

        raise CommandError(
            "Could not find IAM role for backup. Check that a backup plan exists for the session-recording-keys table."
        )

    def _start_restore(
        self,
        backup_client,
        recovery_point_arn: str,
        restored_table_name: str,
        iam_role_arn: str,
    ) -> str:
        self.stdout.write(f"Starting restore to table: {restored_table_name}")

        metadata = {
            "targetTableName": restored_table_name,
            "dynamoDBTargetSettings": json.dumps(
                {
                    "restoreTableToPointInTime": "FALSE",
                    "targetTableName": restored_table_name,
                }
            ),
        }

        response = backup_client.start_restore_job(
            RecoveryPointArn=recovery_point_arn,
            IamRoleArn=iam_role_arn,
            Metadata=metadata,
        )

        restore_job_id = response["RestoreJobId"]
        self.stdout.write(self.style.SUCCESS(f"Restore job started: {restore_job_id}"))
        return restore_job_id

    def _wait_for_restore(self, backup_client, restore_job_id: str) -> None:
        self.stdout.write("Waiting for restore to complete...")
        start_time = time.time()

        while True:
            elapsed = time.time() - start_time
            if elapsed > RESTORE_TIMEOUT_SECONDS:
                raise CommandError(
                    f"Restore timed out after {RESTORE_TIMEOUT_SECONDS}s. "
                    f"Job ID: {restore_job_id} — check AWS console for status."
                )

            response = backup_client.describe_restore_job(RestoreJobId=restore_job_id)
            status = response["Status"]

            if status == "COMPLETED":
                self.stdout.write(self.style.SUCCESS(f"Restore completed in {int(elapsed)}s"))
                return
            elif status in ("ABORTED", "FAILED"):
                message = response.get("StatusMessage", "unknown error")
                raise CommandError(f"Restore job {status}: {message}")

            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            self.stdout.write(f"  Status: {status} ({minutes}m{seconds}s elapsed)")
            time.sleep(RESTORE_POLL_INTERVAL_SECONDS)

    def _query_restored_table(
        self,
        dynamodb_client,
        restored_table_name: str,
        team_id: int,
        session_id: str | None,
    ) -> list[dict]:
        if session_id:
            return self._query_single_key(dynamodb_client, restored_table_name, team_id, session_id)
        else:
            return self._query_team_keys(dynamodb_client, restored_table_name, team_id)

    def _query_single_key(
        self,
        dynamodb_client,
        table_name: str,
        team_id: int,
        session_id: str,
    ) -> list[dict]:
        self.stdout.write(f"Querying restored table for session_id={session_id}, team_id={team_id}")

        response = dynamodb_client.get_item(
            TableName=table_name,
            Key={
                "session_id": {"S": session_id},
                "team_id": {"N": str(team_id)},
            },
        )

        item = response.get("Item")
        if not item:
            self.stdout.write(self.style.WARNING("Key not found in backup"))
            return []

        state = item.get("session_state", {}).get("S", "cleartext")
        if state == "deleted":
            self.stdout.write(self.style.WARNING(f"Key was already deleted in backup (state={state})"))
            return []

        self.stdout.write(self.style.SUCCESS(f"Found key in backup: state={state}"))
        return [item]

    def _query_team_keys(
        self,
        dynamodb_client,
        table_name: str,
        team_id: int,
    ) -> list[dict]:
        self.stdout.write(f"Querying restored table for all keys with team_id={team_id}")

        items: list[dict] = []
        kwargs: dict = {
            "TableName": table_name,
            "IndexName": TEAM_ID_INDEX,
            "KeyConditionExpression": "team_id = :tid",
            "FilterExpression": "session_state <> :deleted",
            "ExpressionAttributeValues": {
                ":tid": {"N": str(team_id)},
                ":deleted": {"S": "deleted"},
            },
        }

        while True:
            response = dynamodb_client.query(**kwargs)
            items.extend(response.get("Items", []))

            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            kwargs["ExclusiveStartKey"] = last_key

        self.stdout.write(self.style.SUCCESS(f"Found {len(items)} restorable keys in backup"))
        return items

    def _restore_items(self, dynamodb_client, items: list[dict], dry_run: bool) -> None:
        if not items:
            self.stdout.write("Nothing to restore")
            return

        restored = 0
        skipped = 0
        restored_session_ids: list[tuple[str, int]] = []

        for item in items:
            session_id = item["session_id"]["S"]
            team_id = int(item["team_id"]["N"])
            state = item.get("session_state", {}).get("S", "cleartext")

            if dry_run:
                self.stdout.write(f"  [DRY RUN] Would restore session_id={session_id} team_id={team_id} state={state}")
                restored += 1
                continue

            try:
                dynamodb_client.put_item(
                    TableName=LIVE_TABLE_NAME,
                    Item=item,
                    ConditionExpression="session_state = :deleted OR attribute_not_exists(session_id)",
                    ExpressionAttributeValues={
                        ":deleted": {"S": "deleted"},
                    },
                )
                self.stdout.write(
                    self.style.SUCCESS(f"  Restored session_id={session_id} team_id={team_id} state={state}")
                )
                restored += 1
                restored_session_ids.append((session_id, team_id))
            except ClientError as e:
                if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    self.stdout.write(
                        f"  Skipped session_id={session_id} team_id={team_id} (not deleted in live table)"
                    )
                    skipped += 1
                else:
                    raise

        if restored_session_ids and not dry_run:
            self._undelete_metadata(restored_session_ids)

        suffix = " (DRY RUN)" if dry_run else ""
        self.stdout.write(self.style.SUCCESS(f"\nDone: {restored} restored, {skipped} skipped{suffix}"))

    def _undelete_metadata(self, session_ids: list[tuple[str, int]]) -> None:
        self.stdout.write("\nUndeleting metadata in ClickHouse and Postgres...")

        session_id_list = [sid for sid, _ in session_ids]
        team_ids = {tid for _, tid in session_ids}

        # UPDATE not DELETE: after a merge, deletion marker and data are one row.
        # DELETE would remove all session metadata. UPDATE rewrites all parts safely.
        sync_execute(
            f"""
            ALTER TABLE sharded_session_replay_events
            ON CLUSTER '{CLICKHOUSE_CLUSTER}'
            UPDATE is_deleted = 0
            WHERE session_id IN %(session_ids)s AND team_id IN %(team_ids)s
            """,
            {"session_ids": session_id_list, "team_ids": list(team_ids)},
        )
        self.stdout.write(f"  ClickHouse: undeleted {len(session_id_list)} sessions")

        # Postgres: bulk update
        updated = SessionRecording.objects.filter(
            session_id__in=session_id_list, team_id__in=team_ids, deleted=True
        ).update(deleted=None)
        self.stdout.write(f"  Postgres: undeleted {updated} recordings")

    def _cleanup(self, dynamodb_client, restored_table_name: str) -> None:
        self.stdout.write(f"Deleting restored table: {restored_table_name}")
        try:
            dynamodb_client.delete_table(TableName=restored_table_name)
            self.stdout.write(self.style.SUCCESS("Restored table deleted"))
        except ClientError as e:
            self.stdout.write(self.style.WARNING(f"Failed to delete restored table: {e}"))
