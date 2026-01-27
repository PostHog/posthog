import time
import asyncio
import logging

from django.conf import settings
from django.core.management.base import BaseCommand

import structlog
from temporalio.common import WorkflowIDReusePolicy

from posthog.temporal.common.client import async_connect
from posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator import (
    RealtimeCohortCalculationCoordinatorWorkflowInputs,
)

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = "Run realtime cohort calculation coordinator to process actions in parallel"

    def add_arguments(self, parser):
        parser.add_argument(
            "--parallelism",
            type=int,
            default=10,
            help="Number of parallel child workflows to spawn (default: 10)",
        )
        parser.add_argument(
            "--workflows-per-batch",
            type=int,
            default=5,
            help="Number of workflows to start per batch for jittered scheduling (default: 5)",
        )
        parser.add_argument(
            "--batch-delay-minutes",
            type=int,
            default=5,
            help="Delay between batches in minutes (default: 5)",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            default=None,
            help="Filter cohorts by team_id (optional)",
        )
        parser.add_argument(
            "--cohort-id",
            type=int,
            default=None,
            help="Filter to a specific cohort_id (optional)",
        )

    def handle(self, *args, **options):
        parallelism = options.get("parallelism", 10)
        workflows_per_batch = options.get("workflows_per_batch", 5)
        batch_delay_minutes = options.get("batch_delay_minutes", 5)
        team_id = options.get("team_id")
        cohort_id = options.get("cohort_id")

        logger.info(
            "Starting realtime cohort calculation coordinator",
            parallelism=parallelism,
            workflows_per_batch=workflows_per_batch,
            batch_delay_minutes=batch_delay_minutes,
            team_id=team_id,
            cohort_id=cohort_id,
        )

        self.run_temporal_workflow(
            parallelism=parallelism,
            workflows_per_batch=workflows_per_batch,
            batch_delay_minutes=batch_delay_minutes,
            team_id=team_id,
            cohort_id=cohort_id,
        )

        logger.info(
            "Coordinator workflow scheduled child workflows",
            parallelism=parallelism,
        )

        self.stdout.write(f"Coordinator workflow scheduled {parallelism} child workflows")
        self.stdout.write("Child workflows are running in the background. Check Temporal UI for progress and results.")

    def run_temporal_workflow(
        self,
        parallelism: int,
        workflows_per_batch: int,
        batch_delay_minutes: int,
        team_id: int | None,
        cohort_id: int | None,
    ) -> None:
        """Run the Temporal workflow for parallel processing."""

        async def _run_workflow():
            # Connect to Temporal
            client = await async_connect()

            # Create coordinator workflow inputs
            inputs = RealtimeCohortCalculationCoordinatorWorkflowInputs(
                parallelism=parallelism,
                workflows_per_batch=workflows_per_batch,
                batch_delay_minutes=batch_delay_minutes,
                team_id=team_id,
                cohort_id=cohort_id,
            )

            # Generate unique workflow ID
            workflow_id = f"realtime-cohort-calculation-coordinator-{int(time.time())}"

            logger.info(f"Starting Temporal coordinator workflow: {workflow_id}")

            try:
                # Start the coordinator workflow (fire-and-forget)
                await client.start_workflow(
                    "realtime-cohort-calculation-coordinator",
                    inputs,
                    id=workflow_id,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                    task_queue=settings.MESSAGING_TASK_QUEUE,
                )

                logger.info(f"Workflow {workflow_id} started successfully")

            except Exception as e:
                logger.exception(f"Workflow execution failed: {e}")
                raise

        try:
            # Run the async function
            asyncio.run(_run_workflow())
        except Exception as e:
            logger.exception(f"Failed to execute Temporal workflow: {e}")
