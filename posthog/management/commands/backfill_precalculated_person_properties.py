import time
import asyncio
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import structlog
from temporalio.common import WorkflowIDReusePolicy

from posthog.models import Cohort
from posthog.models.cohort.cohort import CohortType
from posthog.temporal.common.client import async_connect
from posthog.temporal.messaging.backfill_precalculated_person_properties_coordinator_workflow import (
    BackfillPrecalculatedPersonPropertiesCoordinatorInputs,
)
from posthog.temporal.messaging.filter_storage import store_filters
from posthog.temporal.messaging.types import PersonPropertyFilter

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
        property_key = node.get("key")

        # Skip if missing required fields or if they're empty
        if not condition_hash or not bytecode or not property_key:
            return

        filters.append(
            PersonPropertyFilter(
                condition_hash=condition_hash,
                bytecode=bytecode,
                cohort_ids=[],  # Will be populated during deduplication
                property_key=property_key,
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
            required=False,
            help="Team ID to backfill person properties for. Cannot be used with --team-ids",
        )
        parser.add_argument(
            "--team-ids",
            type=int,
            nargs="+",
            required=False,
            help="List of team IDs to backfill person properties for. Cannot be used with --team-id",
        )
        parser.add_argument(
            "--cohort-id",
            type=int,
            required=False,
            help="Optional: Specific cohort ID to backfill. Can only be used with --team-id, not with --team-ids",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Number of persons to process per batch (default: 1000)",
        )
        parser.add_argument(
            "--concurrent-workflows",
            type=int,
            default=5,
            help="Number of concurrent child workflows to run (default: 5)",
        )
        parser.add_argument(
            "--person-id",
            type=str,
            required=False,
            help="Optional: Specific person ID (UUID) to filter the backfill for. If provided, only processes properties for this person",
        )

    def handle(self, *args, **options):
        team_id = options.get("team_id")
        team_ids_option = options.get("team_ids")
        cohort_id = options.get("cohort_id")
        batch_size = options["batch_size"]
        concurrent_workflows = options["concurrent_workflows"]
        person_id = options.get("person_id")

        # Validate that only one team option is provided
        if team_id and team_ids_option:
            self.stdout.write(self.style.ERROR("Cannot use both --team-id and --team-ids. Please use only one."))
            return

        # Validate that at least one team option is provided
        if not team_id and not team_ids_option:
            self.stdout.write(self.style.ERROR("Must provide either --team-id or --team-ids"))
            return

        # Validate that cohort-id is only used with single team
        if cohort_id and team_ids_option:
            self.stdout.write(
                self.style.ERROR("Cannot use --cohort-id with --team-ids. Use --cohort-id only with --team-id.")
            )
            return

        # Validate that person-id is only used with single team
        if person_id and team_ids_option:
            self.stdout.write(
                self.style.ERROR("Cannot use --person-id with --team-ids. Use --person-id only with --team-id.")
            )
            return

        # Get team IDs to process
        if team_id:
            team_ids = [team_id]
        else:
            # Deduplicate and sort team_ids for deterministic processing
            team_ids = sorted(set(team_ids_option or []))

        self.stdout.write(self.style.SUCCESS(f"Processing {len(team_ids)} team(s): {team_ids}"))

        # Process each team separately (each team needs its own workflow)
        for current_team_id in team_ids:
            self.stdout.write(self.style.SUCCESS(f"\n=== Processing Team {current_team_id} ==="))

            # Get cohorts to process for this team
            if cohort_id:
                # Single cohort mode
                try:
                    cohorts = [Cohort.objects.get(id=cohort_id, team_id=current_team_id)]
                except Cohort.DoesNotExist:
                    raise CommandError(f"Cohort {cohort_id} not found for team {current_team_id}")
            else:
                # All realtime cohorts for team
                cohorts = list(
                    Cohort.objects.filter(
                        team_id=current_team_id,
                        cohort_type=CohortType.REALTIME,
                        deleted=False,
                    ).order_by("id")
                )
                if not cohorts:
                    self.stdout.write(self.style.WARNING(f"No realtime cohorts found for team {current_team_id}"))
                    continue

            if cohort_id:
                self.stdout.write(
                    self.style.SUCCESS(f"Found {len(cohorts)} cohort(s) to evaluate for team {current_team_id}")
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(f"Found {len(cohorts)} realtime cohort(s) to process for team {current_team_id}")
                )

            # Collect and deduplicate filters across all cohorts for this team
            condition_map: dict[str, tuple[list[Any], str | None, set[int]]] = {}
            cohort_ids = []
            total_original_filters = 0
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
                total_original_filters += len(filters)
                self.stdout.write(
                    self.style.SUCCESS(f"Cohort {cohort.id}: found {len(filters)} person property filters")
                )

                # Deduplicate by condition_hash
                for f in filters:
                    if f.condition_hash not in condition_map:
                        condition_map[f.condition_hash] = (f.bytecode, f.property_key, {cohort.id})
                        self.stdout.write(f"  + New condition: {f.condition_hash}")
                    else:
                        # Condition already exists, just add this cohort ID
                        condition_map[f.condition_hash][2].add(cohort.id)
                        self.stdout.write(f"  = Duplicate condition: {f.condition_hash}")

            if not condition_map:
                self.stdout.write(
                    self.style.WARNING(
                        f"No person property filters found across any cohorts for team {current_team_id}"
                    )
                )
                continue

            # Convert to list of PersonPropertyFilter objects with deterministic ordering
            deduplicated_filters = [
                PersonPropertyFilter(
                    condition_hash=condition_hash,
                    bytecode=bytecode,
                    property_key=property_key,
                    cohort_ids=sorted(cohort_set),  # Sort cohort IDs for deterministic order
                )
                for condition_hash, (bytecode, property_key, cohort_set) in sorted(
                    condition_map.items()
                )  # Sort by condition_hash for deterministic order
            ]

            # Sort cohort_ids for deterministic workflow ordering
            cohort_ids = sorted(cohort_ids)

            self.stdout.write(
                self.style.SUCCESS(
                    f"\nDeduplicated {len(deduplicated_filters)} unique conditions across {len(cohort_ids)} cohorts"
                )
            )
            for filter_obj in deduplicated_filters:
                self.stdout.write(f"  - {filter_obj.condition_hash} (used by cohorts: {filter_obj.cohort_ids})")

            # Run coordinator workflow with cursor-based sequential processing
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nProcessing {len(cohort_ids)} cohorts: reduced {total_original_filters} filters to {len(deduplicated_filters)} unique conditions"
                )
            )

            try:
                workflow_id = self.run_temporal_workflow(
                    team_id=current_team_id,
                    filters=deduplicated_filters,
                    cohort_ids=cohort_ids,
                    batch_size=batch_size,
                    concurrent_workflows=concurrent_workflows,
                    person_id=person_id,
                )
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Failed to start workflow for team {current_team_id}: {e}"))
                continue

            self.stdout.write(
                self.style.SUCCESS(
                    f"\nSuccessfully started coordinator workflow for team {current_team_id}\n"
                    f"  Workflow ID: {workflow_id}\n"
                    f"  Cohorts: {cohort_ids}\n"
                    f"  Unique conditions: {len(deduplicated_filters)}\n"
                    f"  Batch size: {batch_size} persons per batch\n"
                    f"  Concurrent workflows: {concurrent_workflows}"
                )
            )
            self.stdout.write(
                f"\nWorkflow is running with {concurrent_workflows} concurrent child workflows using ID-range based batching. Check Temporal UI for progress and results."
            )

    def run_temporal_workflow(
        self,
        team_id: int,
        filters: list[PersonPropertyFilter],
        cohort_ids: list[int],
        batch_size: int,
        concurrent_workflows: int,
        person_id: str | None = None,
    ) -> str:
        """Run the Temporal coordinator workflow for the team."""

        async def _run_workflow():
            # Connect to Temporal
            client = await async_connect()

            # Store filters in Redis and get storage key
            filter_storage_key = store_filters(filters, team_id)
            self.stdout.write(
                self.style.SUCCESS(f"Stored {len(filters)} filters in Redis with key: {filter_storage_key}")
            )

            # Create coordinator workflow inputs with filter storage key
            inputs = BackfillPrecalculatedPersonPropertiesCoordinatorInputs(
                team_id=team_id,
                filter_storage_key=filter_storage_key,
                cohort_ids=cohort_ids,
                batch_size=batch_size,
                concurrent_workflows=concurrent_workflows,
                person_id=person_id,
                single_cohort_mode=len(cohort_ids) == 1,  # True when exactly one cohort is being processed
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
