import time
import asyncio
import logging

from django.core.management.base import BaseCommand

import structlog
from temporalio.common import WorkflowIDReusePolicy

from posthog.constants import MESSAGING_TASK_QUEUE
from posthog.temporal.common.client import async_connect
from posthog.temporal.messaging.actions_workflow_coordinator import ActionsCoordinatorWorkflowInputs

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = "Run actions workflow coordinator to process actions in parallel"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Number of days to look back (default: 30)",
        )
        parser.add_argument(
            "--min-matches",
            type=int,
            default=3,
            help="Minimum number of matches required (default: 3)",
        )
        parser.add_argument(
            "--parallelism",
            type=int,
            default=10,
            help="Number of parallel child workflows to spawn (default: 10)",
        )

    def handle(self, *args, **options):
        days = options.get("days", 30)
        min_matches = options.get("min_matches", 3)
        parallelism = options.get("parallelism", 10)

        logger.info(
            "Starting actions processing coordinator",
            days=days,
            min_matches=min_matches,
            parallelism=parallelism,
        )

        self.run_temporal_workflow(
            days=days,
            min_matches=min_matches,
            parallelism=parallelism,
        )

        logger.info(
            "Coordinator workflow scheduled child workflows",
            parallelism=parallelism,
        )

        self.stdout.write(f"Coordinator workflow scheduled {parallelism} child workflows")
        self.stdout.write("Child workflows are running in the background. Check Temporal UI for progress and results.")

    def run_temporal_workflow(
        self,
        days: int,
        min_matches: int,
        parallelism: int,
    ) -> None:
        """Run the Temporal workflow for parallel processing."""

        async def _run_workflow():
            # Connect to Temporal
            client = await async_connect()

            # Create coordinator workflow inputs
            inputs = ActionsCoordinatorWorkflowInputs(
                days=days,
                min_matches=min_matches,
                parallelism=parallelism,
            )

            # Generate unique workflow ID
            workflow_id = f"actions-coordinator-{int(time.time())}"

            logger.info(f"Starting Temporal coordinator workflow: {workflow_id}")

            try:
                # Execute the coordinator workflow (no result expected)
                await client.execute_workflow(
                    "actions-coordinator",
                    inputs,
                    id=workflow_id,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                    task_queue=MESSAGING_TASK_QUEUE,
                )

                logger.info(f"Workflow {workflow_id} completed successfully")

            except Exception as e:
                logger.exception(f"Workflow execution failed: {e}")
                raise

        try:
            # Run the async function
            asyncio.run(_run_workflow())
        except Exception as e:
            logger.exception(f"Failed to execute Temporal workflow: {e}")
