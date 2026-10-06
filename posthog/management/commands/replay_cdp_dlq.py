import asyncio
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.cdp_dlq_replay.workflow import REPLAY_WORKFLOW_ID, CdpDlqReplayInputs, CdpDlqReplayWorkflow
from posthog.temporal.common.client import async_connect


class Command(BaseCommand):
    help = "Replay the events the CDP events consumer parked on its dead-letter topic, once the cause is fixed"

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-unreplayable",
            action="store_true",
            help="Commit past a record that still cannot be replayed, and list it, instead of stopping at it",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            asyncio.run(start_replay(CdpDlqReplayInputs(skip_unreplayable=options["skip_unreplayable"])))
        except WorkflowAlreadyStartedError:
            raise CommandError(f"A replay is already running. Find {REPLAY_WORKFLOW_ID} in the Temporal UI.")
        self.stdout.write(f"Started {REPLAY_WORKFLOW_ID}. Progress and the result are in the Temporal UI.")


async def start_replay(inputs: CdpDlqReplayInputs) -> None:
    client = await async_connect()
    await client.start_workflow(
        CdpDlqReplayWorkflow.run,
        inputs,
        id=REPLAY_WORKFLOW_ID,
        task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        # A finished or failed replay can run again: the committed offsets decide what it reads.
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
    )
