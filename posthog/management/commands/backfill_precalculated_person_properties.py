import time
import asyncio

from django.conf import settings
from django.core.management.base import BaseCommand

import structlog
from temporalio.common import WorkflowIDReusePolicy

from posthog.models import Cohort
from posthog.models.cohort.cohort import CohortType
from posthog.temporal.common.client import async_connect
from posthog.temporal.messaging.backfill_precalculated_person_properties_coordinator_workflow import (
    BackfillPrecalculatedPersonPropertiesCoordinatorInputs,
)
from posthog.temporal.messaging.backfill_precalculated_person_properties_workflow import (
    CohortFilters,
    PersonPropertyFilter,
)

logger = structlog.get_logger(__name__)


def extract_person_property_filters(cohort: Cohort) -> list[PersonPropertyFilter]:
    """
    Extract person property filters from a realtime cohort.

    Recursively traverses the filter tree to find all person property filters
    with conditionHash and bytecode.

    Returns a list of PersonPropertyFilter objects suitable for passing to the workflow.
    """
    filters: list[PersonPropertyFilter] = []

    if not cohort.filters:
        return filters

    properties = cohort.filters.get("properties")
    if not properties:
        return filters

    def traverse_filter_tree(node):
        """Recursively traverse the filter tree to find person property filters."""
        if not isinstance(node, dict):
            return

        # Check if this is a group node (AND/OR)
        node_type = node.get("type")
        if node_type in ("AND", "OR"):
            # Recursively process children
            for child in node.get("values", []):
                traverse_filter_tree(child)
            return

        # This is a leaf node - check if it's a person property filter
        if node_type != "person":
            return

        condition_hash = node.get("conditionHash")
        bytecode = node.get("bytecode")

        # Skip if missing required fields or if they're empty
        if not condition_hash or not bytecode:
            return

        filters.append(
            PersonPropertyFilter(
                condition_hash=condition_hash,
                bytecode=bytecode,
            )
        )

    # Start traversal from the root properties node
    traverse_filter_tree(properties)

    return filters


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

        # Collect and deduplicate filters across all cohorts
        # Map: condition_hash -> (bytecode, [cohort_ids])
        condition_map: dict[str, tuple[list, list[int]]] = {}
        cohort_ids = []

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

            cohort_ids.append(cohort.id)
            self.stdout.write(self.style.SUCCESS(f"Cohort {cohort.id}: found {len(filters)} person property filters"))

            # Deduplicate by condition_hash
            for f in filters:
                if f.condition_hash not in condition_map:
                    condition_map[f.condition_hash] = (f.bytecode, [cohort.id])
                    self.stdout.write(f"  + New condition: {f.condition_hash}")
                else:
                    # Condition already exists, just add this cohort ID
                    condition_map[f.condition_hash][1].append(cohort.id)
                    self.stdout.write(f"  = Duplicate condition: {f.condition_hash}")

        if not condition_map:
            self.stdout.write(self.style.WARNING("No person property filters found across any cohorts"))
            return

        # Build deduplicated filter list and create cohort filters
        deduplicated_filters = [
            PersonPropertyFilter(
                condition_hash=cond_hash,
                bytecode=bytecode,
            )
            for cond_hash, (bytecode, _cids) in condition_map.items()
        ]

        # Create a single CohortFilters object with all deduplicated filters
        # All cohorts will process the same deduplicated filter set
        cohort_filters_list = [
            CohortFilters(
                cohort_id=cohort_id,
                filters=deduplicated_filters,  # All cohorts get the same deduplicated filters
            )
            for cohort_id in cohort_ids
        ]

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDeduplicated {len(deduplicated_filters)} unique conditions across {len(cohort_ids)} cohorts"
            )
        )
        for cond_hash, (_, cids) in condition_map.items():
            self.stdout.write(f"  - {cond_hash} (used by cohorts: {cids})")

        # Run single coordinator workflow for all cohorts with deduplicated filters
        total_original_filters = sum(len(extract_person_property_filters(cohorts[i])) for i in range(len(cohort_ids)))
        self.stdout.write(
            self.style.SUCCESS(
                f"\nProcessing {len(cohort_ids)} cohorts: reduced {total_original_filters} filters to {len(deduplicated_filters)} unique conditions"
            )
        )

        workflow_id = self.run_temporal_workflow(
            team_id=team_id,
            cohort_filters=cohort_filters_list,
            parallelism=parallelism,
            batch_size=batch_size,
            workflows_per_batch=workflows_per_batch,
            batch_delay_minutes=batch_delay_minutes,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nSuccessfully started single coordinator workflow for team {team_id}\n"
                f"  Workflow ID: {workflow_id}\n"
                f"  Cohorts: {[cf.cohort_id for cf in cohort_filters_list]}\n"
                f"  Unique conditions: {len(deduplicated_filters)}\n"
                f"  Parallelism: {parallelism} workers"
            )
        )
        self.stdout.write(
            "\nChild workflows are running in the background. Check Temporal UI for progress and results."
        )

    def run_temporal_workflow(
        self,
        team_id: int,
        cohort_filters: list[CohortFilters],
        parallelism: int,
        batch_size: int,
        workflows_per_batch: int,
        batch_delay_minutes: int,
    ) -> str:
        """Run the Temporal coordinator workflow for the team."""

        async def _run_workflow():
            # Connect to Temporal
            client = await async_connect()

            # Create coordinator workflow inputs
            inputs = BackfillPrecalculatedPersonPropertiesCoordinatorInputs(
                team_id=team_id,
                cohort_filters=cohort_filters,
                parallelism=parallelism,
                batch_size=batch_size,
                workflows_per_batch=workflows_per_batch,
                batch_delay_minutes=batch_delay_minutes,
            )

            # Generate unique workflow ID (one per team, based on timestamp)
            workflow_id = f"backfill-precalculated-person-properties-team-{team_id}-{int(time.time())}"

            try:
                # Start the coordinator workflow (fire-and-forget)
                await client.start_workflow(
                    "backfill-precalculated-person-properties-coordinator",
                    inputs,
                    id=workflow_id,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                    task_queue=settings.MESSAGING_TASK_QUEUE,
                )

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
