import json
import asyncio
from dataclasses import asdict
from datetime import datetime
from typing import cast

from django.core.management.base import BaseCommand, CommandError, CommandParser

from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError

from products.customer_analytics.backend.facade import membership_snapshot
from products.customer_analytics.backend.facade.membership_snapshot_contracts import MembershipSnapshotInput


class Command(BaseCommand):
    help = "Load a frozen eligibility snapshot into memberships through a one-off worker workflow. Defaults to dry-run"

    def add_arguments(self, parser: CommandParser) -> None:
        commands = parser.add_subparsers(dest="action", required=True)
        for action in ("start", "status", "resume", "cancel"):
            command = commands.add_parser(action)
            command.add_argument("--team-id", type=int, required=True)
            if action == "start":
                command.add_argument("--source-view-id", required=True)
                command.add_argument("--source-job-id", required=True)
                command.add_argument("--group-type-index", type=int, required=True)
                command.add_argument("--checked-at", required=True)
                command.add_argument("--expected-rows", type=int, required=True)
                command.add_argument("--max-rows", type=int, default=500)
                command.add_argument("--membership-version", type=int, default=0)
                command.add_argument("--batch-size", type=int, default=5_000)
                command.add_argument(
                    "--execute", action="store_true", help="Append native membership rows instead of a dry-run"
                )

    @staticmethod
    async def get_output(action: str, team_id: int, input: MembershipSnapshotInput | None) -> str:
        if action == "start":
            if input is None:
                raise ValueError("Supply the source snapshot parameters")
            run_id = await membership_snapshot.start(input)
            return json.dumps({"run_id": run_id, "dry_run": input.dry_run, "max_rows": input.max_rows})
        if action == "status":
            return json.dumps(asdict(await membership_snapshot.get_status(team_id)))
        if action == "resume":
            await membership_snapshot.resume(team_id)
            return "Resume requested"
        await membership_snapshot.cancel(team_id)
        return "Cancel requested. The current activity can finish before stopping"

    def handle(self, *args: object, **options: object) -> None:
        action = cast(str, options["action"])
        team_id = cast(int, options["team_id"])
        try:
            input = (
                MembershipSnapshotInput(
                    team_id=team_id,
                    group_type_index=cast(int, options["group_type_index"]),
                    source_view_id=cast(str, options["source_view_id"]),
                    source_job_id=cast(str, options["source_job_id"]),
                    checked_at=datetime.fromisoformat(cast(str, options["checked_at"])),
                    expected_rows=cast(int, options["expected_rows"]),
                    max_rows=cast(int, options["max_rows"]),
                    membership_version=cast(int, options["membership_version"]),
                    dry_run=not options["execute"],
                    batch_size=cast(int, options["batch_size"]),
                )
                if action == "start"
                else None
            )
            output = asyncio.run(self.get_output(action, team_id, input))
        except WorkflowAlreadyStartedError as error:
            raise CommandError("A snapshot backfill is active. Use status, resume, or cancel") from error
        except (RPCError, ValueError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(output)
