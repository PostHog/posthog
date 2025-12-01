import time
import asyncio
import logging

from django.conf import settings
from django.core.management.base import BaseCommand

import structlog
from temporalio.common import WorkflowIDReusePolicy

from posthog.models import Cohort
from posthog.models.cohort.cohort import CohortType
from posthog.models.cohort.precalculate_person_properties import extract_person_property_filters
from posthog.temporal.common.client import async_connect
from posthog.temporal.messaging.precalculate_person_properties_workflow_coordinator import (
    PrecalculatePersonPropertiesCoordinatorWorkflowInputs,
)

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = "Backfill precalculated_person_properties table for realtime cohorts with person property filters"

    def add_arguments(self, parser):
        parser.add_argument(
            "--cohort-id",
            type=int,
            required=True,
            help="Cohort ID to backfill person properties for",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            required=True,
            help="Team ID for the cohort",
        )
        parser.add_argument(
            "--parallelism",
            type=int,
            default=5,
            help="Number of parallel child workflows to spawn (default: 5)",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Number of persons to process per batch within each worker (default: 1000)",
        )
        parser.add_argument(
            "--workflows-per-batch",
            type=int,
            default=10,
            help="Number of workflows to start per batch for jittered scheduling (default: 10)",
        )
        parser.add_argument(
            "--batch-delay-minutes",
            type=int,
            default=1,
            help="Delay between batches in minutes (default: 1)",
        )

    def handle(self, *args, **options):
        cohort_id = options["cohort_id"]
        team_id = options["team_id"]
        parallelism = options["parallelism"]
        batch_size = options["batch_size"]
        workflows_per_batch = options["workflows_per_batch"]
        batch_delay_minutes = options["batch_delay_minutes"]

        # Validate cohort exists and is realtime
        try:
            cohort = Cohort.objects.get(id=cohort_id, team_id=team_id)
        except Cohort.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Cohort {cohort_id} not found for team {team_id}"))
            return

        if cohort.cohort_type != CohortType.REALTIME:
            self.stdout.write(
                self.style.ERROR(f"Cohort {cohort_id} is not a realtime cohort (type: {cohort.cohort_type})")
            )
            return

        # Extract person property filters
        filters = extract_person_property_filters(cohort)
        if not filters:
            self.stdout.write(
                self.style.WARNING(f"Cohort {cohort_id} has no person property filters with conditionHash and bytecode")
            )
            return

        self.stdout.write(self.style.SUCCESS(f"Found {len(filters)} person property filters for cohort {cohort_id}"))
        for f in filters:
            self.stdout.write(f"  - conditionHash: {f.condition_hash}")

        logger.info(
            "Starting person properties backfill coordinator",
            cohort_id=cohort_id,
            team_id=team_id,
            filter_count=len(filters),
            parallelism=parallelism,
            batch_size=batch_size,
            workflows_per_batch=workflows_per_batch,
            batch_delay_minutes=batch_delay_minutes,
        )

        workflow_id = self.run_temporal_workflow(
            cohort=cohort,
            filters=filters,
            parallelism=parallelism,
            batch_size=batch_size,
            workflows_per_batch=workflows_per_batch,
            batch_delay_minutes=batch_delay_minutes,
        )

        self.stdout.write(
            self.style.SUCCESS(f"Coordinator workflow '{workflow_id}' scheduled {parallelism} child workflows")
        )
        self.stdout.write("Child workflows are running in the background. Check Temporal UI for progress and results.")
        self.stdout.write(f"Temporal UI: http://localhost:8233/namespaces/default/workflows/{workflow_id}")

    def run_temporal_workflow(
        self,
        cohort: Cohort,
        filters: list,
        parallelism: int,
        batch_size: int,
        workflows_per_batch: int,
        batch_delay_minutes: int,
    ) -> str:
        """Run the Temporal workflow for parallel processing."""

        async def _run_workflow():
            # Connect to Temporal
            client = await async_connect()

            # Create coordinator workflow inputs
            inputs = PrecalculatePersonPropertiesCoordinatorWorkflowInputs(
                team_id=cohort.team_id,
                cohort_id=cohort.id,
                filters=filters,
                parallelism=parallelism,
                batch_size=batch_size,
                workflows_per_batch=workflows_per_batch,
                batch_delay_minutes=batch_delay_minutes,
            )

            # Generate unique workflow ID
            workflow_id = f"precalculate-person-properties-{cohort.id}-{cohort.team_id}-{int(time.time())}"

            logger.info(f"Starting Temporal coordinator workflow: {workflow_id}")

            try:
                # Start the coordinator workflow (fire-and-forget)
                await client.start_workflow(
                    "precalculate-person-properties-coordinator",
                    inputs,
                    id=workflow_id,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                    task_queue=settings.MESSAGING_TASK_QUEUE,
                )

                logger.info(f"Workflow {workflow_id} started successfully")
                return workflow_id

            except Exception as e:
                logger.exception(f"Workflow execution failed: {e}")
                raise

        try:
            # Run the async function
            return asyncio.run(_run_workflow())
        except Exception as e:
            logger.exception(f"Failed to execute Temporal workflow: {e}")
            raise
