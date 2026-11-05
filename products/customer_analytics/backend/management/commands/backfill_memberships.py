import json
import asyncio
from dataclasses import asdict
from typing import cast

from django.core.management.base import BaseCommand, CommandError, CommandParser

from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError

from posthog.models.team import Team

from products.customer_analytics.backend.logic.membership_backfill import get_membership_group_type_index
from products.customer_analytics.backend.logic.membership_backfill_control import MembershipBackfillControl


class Command(BaseCommand):
    help = "Start, inspect, resume, or cancel an account membership backfill"

    def add_arguments(self, parser: CommandParser) -> None:
        commands = parser.add_subparsers(dest="action", required=True)
        for action in ("start", "status", "resume", "cancel"):
            command = commands.add_parser(action)
            command.add_argument("--team-id", type=int, required=True)
            if action == "start":
                scope = command.add_mutually_exclusive_group(required=True)
                scope.add_argument("--all-accounts", action="store_true")
                scope.add_argument("--account", action="append", dest="accounts")
                command.add_argument("--dry-run", action="store_true")

    def handle(self, *args: object, **options: object) -> None:
        team_id = cast(int, options["team_id"])
        action = cast(str, options["action"])
        accounts = tuple(sorted(set(cast(list[str], options.get("accounts") or []))))
        dry_run = bool(options.get("dry_run"))
        if action == "start":
            if any(not key or len(key.encode("utf-8")) > 1024 for key in accounts) or len(accounts) > 100:
                raise CommandError("Supply at most 100 nonempty account keys, each within 1024 bytes")
            team = Team.objects.filter(id=team_id).first()
            if team is None:
                raise CommandError("Project does not exist")
            try:
                index = get_membership_group_type_index(team)
            except RuntimeError as error:
                raise CommandError(str(error)) from error
            if index is None:
                raise CommandError("Customer analytics must be active with a valid account group type")
        try:
            output = asyncio.run(self.get_output(action, team_id, accounts, dry_run=dry_run))
        except WorkflowAlreadyStartedError as error:
            raise CommandError(
                "A backfill is already active for this project. Use status, resume, or cancel"
            ) from error
        except (RPCError, ValueError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(output)

    @staticmethod
    async def get_output(action: str, team_id: int, accounts: tuple[str, ...], *, dry_run: bool) -> str:
        control = await MembershipBackfillControl.connect()
        if action == "start":
            run_id = await control.start(team_id, account_keys=accounts, dry_run=dry_run)
            return json.dumps({"team_id": team_id, "run_id": run_id, "status": "starting", "dry_run": dry_run})
        if action == "status":
            return json.dumps(asdict(await control.get_status(team_id)), default=str)
        if action == "resume":
            await control.resume(team_id)
            return "Resume requested"
        await control.cancel(team_id)
        return "Cancel requested. The current batch can finish before the backfill stops"
