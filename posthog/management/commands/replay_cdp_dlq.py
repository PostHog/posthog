import json
import asyncio
import datetime as dt
import dataclasses
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from temporalio.client import WorkflowHandle
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.cdp_dlq_replay.workflow import CdpDlqReplayInputs, CdpDlqReplayWorkflow, replay_workflow_id
from posthog.temporal.common.client import async_connect


class Command(BaseCommand):
    help = "Replay events the CDP events consumer parked on its dead-letter topic, once the cause is fixed"

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="action", required=True, metavar="action")

        start = sub.add_parser("start", help="Start a replay of the records parked in a time window")
        start.add_argument("--start", required=True, help="ISO datetime. Records parked before it are not read.")
        start.add_argument("--end", help="ISO datetime. Defaults to now.")
        start.add_argument("--team-id", type=int, help="Only replay this team's records")
        start.add_argument(
            "--source-id",
            action="append",
            default=[],
            dest="source_ids",
            help="Only replay for this hog function or hog flow id. Repeat for several.",
        )
        start.add_argument("--dry-run", action="store_true", help="Count the records in scope and rebuild nothing")
        start.add_argument(
            "--skip-unreplayable",
            action="store_true",
            help="List a record that cannot be replayed and move past it, instead of waiting for retry or skip",
        )
        start.add_argument("--batch-size", type=int, default=500)

        status = sub.add_parser("status", help="Show where each partition of a replay is")
        status.add_argument("workflow_id")

        for action, description in (
            ("retry", "Replay the blocked record again, once the fix is deployed"),
            ("skip", "List the blocked record as skipped and move past it"),
        ):
            decide = sub.add_parser(action, help=description)
            decide.add_argument("workflow_id")
            decide.add_argument("--partition", type=int, help="Defaults to every blocked partition")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["action"] == "start":
            inputs = CdpDlqReplayInputs(
                start_timestamp=options["start"],
                # Resolved here rather than in the workflow, so the id names a fixed window.
                end_timestamp=options["end"] or dt.datetime.now(dt.UTC).isoformat(),
                team_id=options["team_id"],
                source_ids=options["source_ids"],
                dry_run=options["dry_run"],
                skip_unreplayable=options["skip_unreplayable"],
                batch_size=options["batch_size"],
            )
            workflow_id = asyncio.run(start_replay(inputs))
            self.stdout.write(f"Started {workflow_id}")
            self.stdout.write(f"  python manage.py replay_cdp_dlq status {workflow_id}")
            return

        if options["action"] == "status":
            self.stdout.write(json.dumps(asyncio.run(replay_status(options["workflow_id"])), indent=2))
            return

        asyncio.run(decide(options["workflow_id"], options["action"], options["partition"]))
        self.stdout.write(f"Sent {options['action']} to {options['workflow_id']}")


async def start_replay(inputs: CdpDlqReplayInputs) -> str:
    client = await async_connect()
    workflow_id = replay_workflow_id(inputs)
    try:
        await client.start_workflow(
            CdpDlqReplayWorkflow.run,
            inputs,
            id=workflow_id,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            # A dry run reads and counts, so running it twice is harmless. A real run delivers, and
            # running the same window twice delivers it twice.
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE
            if inputs.dry_run
            else WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
    except WorkflowAlreadyStartedError:
        raise CommandError(
            f"{workflow_id} already ran or is running for this window and scope. "
            f"Check it with: python manage.py replay_cdp_dlq status {workflow_id}"
        )
    return workflow_id


async def replay_status(workflow_id: str) -> list[dict[str, Any]]:
    handle: WorkflowHandle = (await async_connect()).get_workflow_handle(workflow_id)
    return [dataclasses.asdict(partition) for partition in await handle.query(CdpDlqReplayWorkflow.status)]


async def decide(workflow_id: str, action: str, partition: int | None) -> None:
    handle: WorkflowHandle = (await async_connect()).get_workflow_handle(workflow_id)
    signal = CdpDlqReplayWorkflow.retry if action == "retry" else CdpDlqReplayWorkflow.skip
    await handle.signal(signal, partition)
