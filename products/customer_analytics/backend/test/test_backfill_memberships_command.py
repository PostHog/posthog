import io
import json
from types import SimpleNamespace

from unittest.mock import AsyncMock, MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from parameterized import parameterized
from temporalio.client import WorkflowExecutionStatus

from products.customer_analytics.backend.logic.membership_backfill import MembershipTeam

COMMAND = "products.customer_analytics.backend.management.commands.backfill_memberships"
CONTROL = "products.customer_analytics.backend.logic.membership_backfill_control"


class TestBackfillMembershipsCommand(SimpleTestCase):
    @parameterized.expand(
        [
            (scope, accounts, dry_run)
            for scope, accounts in (
                (["--all-accounts"], ()),
                (["--account", "b", "--account", "a", "--account", "b"], ("a", "b")),
            )
            for dry_run in (False, True)
        ]
    )
    def test_start_preserves_account_scope(
        self, scope: list[str], expected_accounts: tuple[str, ...], dry_run: bool
    ) -> None:
        client = AsyncMock()
        client.start_workflow.return_value.first_execution_run_id = "example-run"
        output = io.StringIO()
        with (
            patch(f"{COMMAND}.Team.objects.filter"),
            patch(f"{COMMAND}.get_membership_group_type_index", return_value=0),
            patch(f"{CONTROL}.async_connect", return_value=client),
        ):
            call_command("backfill_memberships", "start", "--team-id", "17", *scope, dry_run=dry_run, stdout=output)
        assert json.loads(output.getvalue())["run_id"] == "example-run"
        assert client.start_workflow.call_args.args[1] == MembershipTeam(
            team_id=17,
            account_keys=expected_accounts,
            dry_run=dry_run,
        )


class TestBackfillMembershipSnapshotCommand(SimpleTestCase):
    @parameterized.expand([(False, 0), (True, 19), (True, 0)])
    def test_start_defaults_to_dry_run_and_requires_a_version_for_writes(self, execute: bool, version: int) -> None:
        client = MagicMock()
        client.start_workflow = AsyncMock(return_value=SimpleNamespace(first_execution_run_id="example-snapshot-run"))
        client.get_schedule_handle.return_value.describe = AsyncMock(
            return_value=SimpleNamespace(schedule=SimpleNamespace(state=SimpleNamespace(paused=True)))
        )
        client.get_workflow_handle.return_value.describe = AsyncMock(
            return_value=SimpleNamespace(status=WorkflowExecutionStatus.COMPLETED)
        )
        args = [
            "backfill_membership_snapshot",
            "start",
            "--team-id",
            "17",
            "--group-type-index",
            "1",
            "--source-view-id",
            "00000000-0000-4000-8000-000000000020",
            "--source-job-id",
            "00000000-0000-4000-8000-000000000021",
            "--checked-at",
            "2024-05-04T12:00:00.123456+00:00",
            "--expected-rows",
            "1000",
            "--membership-version",
            str(version),
        ]
        if execute:
            args.append("--execute")
        output = io.StringIO()
        with (
            patch(
                "products.customer_analytics.backend.logic.membership_snapshot_control.async_connect",
                return_value=client,
            ),
            patch(
                "products.customer_analytics.backend.temporal.membership_snapshot_backfill.async_connect",
                return_value=client,
            ),
        ):
            if execute and version == 0:
                with self.assertRaises(CommandError):
                    call_command(*args, stdout=output)
                client.start_workflow.assert_not_awaited()
                return
            call_command(*args, stdout=output)
        started = client.start_workflow.call_args.args[1]
        assert started.dry_run is not execute
        assert started.max_rows == 500
        assert started.membership_version == version
        assert json.loads(output.getvalue())["dry_run"] is not execute
