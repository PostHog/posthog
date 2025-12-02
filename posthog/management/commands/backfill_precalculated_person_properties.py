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
from posthog.temporal.messaging.backfill_precalculated_person_properties_coordinator_workflow import (
    BackfillPrecalculatedPersonPropertiesCoordinatorInputs,
)

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = "Backfill precalculated_person_properties table for realtime cohorts with person property filters"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=int,
            required=True,
            help="Team ID to backfill person properties for",
        )
        parser.add_argument(
            "--cohort-id",
            type=int,
            required=False,
            help="Optional: Specific cohort ID to backfill. If not provided, backfills all realtime cohorts for the team",
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
        team_id = options["team_id"]
        cohort_id = options.get("cohort_id")
        parallelism = options["parallelism"]
        batch_size = options["batch_size"]
        workflows_per_batch = options["workflows_per_batch"]
        batch_delay_minutes = options["batch_delay_minutes"]

        # Get cohorts to process
        if cohort_id:
            # Single cohort mode
            try:
                cohorts = [Cohort.objects.get(id=cohort_id, team_id=team_id)]
            except Cohort.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"Cohort {cohort_id} not found for team {team_id}"))
                return
        else:
            # All realtime cohorts for team
            cohorts = list(
                Cohort.objects.filter(
                    team_id=team_id,
                    cohort_type=CohortType.REALTIME,
                    deleted=False,
                ).order_by("id")
            )
            if not cohorts:
                self.stdout.write(self.style.WARNING(f"No realtime cohorts found for team {team_id}"))
                return

        self.stdout.write(self.style.SUCCESS(f"Found {len(cohorts)} realtime cohort(s) to process for team {team_id}"))

        # Process each cohort
        workflow_ids = []
        for cohort in cohorts:
            if cohort.cohort_type != CohortType.REALTIME:
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping cohort {cohort.id}: not a realtime cohort (type: {cohort.cohort_type})"
                    )
                )
                continue

            # Extract person property filters
            filters = extract_person_property_filters(cohort)
            if not filters:
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping cohort {cohort.id}: no person property filters with conditionHash and bytecode"
                    )
                )
                continue

            self.stdout.write(
                self.style.SUCCESS(f"Processing cohort {cohort.id}: found {len(filters)} person property filters")
            )
            for f in filters:
                self.stdout.write(f"  - conditionHash: {f.condition_hash}")

            logger.info(
                "Starting person properties backfill coordinator",
                cohort_id=cohort.id,
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

            workflow_ids.append((cohort.id, workflow_id))
            self.stdout.write(
                self.style.SUCCESS(
                    f"Cohort {cohort.id}: Coordinator workflow '{workflow_id}' scheduled {parallelism} child workflows"
                )
            )

        self.stdout.write(self.style.SUCCESS(f"\nSuccessfully started {len(workflow_ids)} coordinator workflow(s)"))
        for cohort_id, workflow_id in workflow_ids:
            self.stdout.write(f"  Cohort {cohort_id}: {workflow_id}")
        self.stdout.write(
            "\nChild workflows are running in the background. Check Temporal UI for progress and results."
        )
        if workflow_ids:
            self.stdout.write(f"Temporal UI: http://localhost:8233/namespaces/default/workflows")

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
            inputs = BackfillPrecalculatedPersonPropertiesCoordinatorInputs(
                team_id=cohort.team_id,
                cohort_id=cohort.id,
                filters=filters,
                parallelism=parallelism,
                batch_size=batch_size,
                workflows_per_batch=workflows_per_batch,
                batch_delay_minutes=batch_delay_minutes,
            )

            # Generate unique workflow ID
            workflow_id = f"backfill-precalculated-person-properties-{cohort.id}-{cohort.team_id}-{int(time.time())}"

            logger.info(f"Starting Temporal coordinator workflow: {workflow_id}")

            try:
                # Start the coordinator workflow (fire-and-forget)
                await client.start_workflow(
                    "backfill-precalculated-person-properties-coordinator",
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
