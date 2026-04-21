import datetime as dt
import dataclasses
from typing import Any

from django.core.management.base import BaseCommand, CommandError

import structlog

from posthog.models import Cohort
from posthog.models.cohort.cohort import CohortType
from posthog.models.property.property import BehavioralPropertyType
from posthog.temporal.messaging.filter_storage import store_event_filters
from posthog.temporal.messaging.types import BehavioralEventFilter

logger = structlog.get_logger(__name__)


@dataclasses.dataclass
class _DeduplicatedCondition:
    """Accumulator for deduplicating behavioral filters across cohorts."""

    bytecode: list[Any]
    event_name: str
    time_value: int
    time_interval: str
    event_filters: list[dict] | None
    cohort_ids: set[int]


# Behavioral filter types that can be compiled to bytecode for realtime evaluation
SUPPORTED_BEHAVIORAL_TYPES = {
    BehavioralPropertyType.PERFORMED_EVENT,
    BehavioralPropertyType.PERFORMED_EVENT_MULTIPLE,
}

# Hard cap on backfill window to prevent runaway scans. Raise after benchmarking.
MAX_BACKFILL_DAYS = 90

# Supported time_interval values and their conversion to days
TIME_INTERVAL_TO_DAYS = {
    "day": 1,
    "week": 7,
    "month": 30,
    "year": 365,
}


def extract_behavioral_filters(cohort: Cohort) -> list[BehavioralEventFilter]:
    """Extract behavioral event filters from a realtime cohort.

    Recursively traverses the filter tree to find behavioral filters with
    conditionHash and bytecode that can be used for event backfilling.
    Only extracts performed_event and performed_event_multiple types.
    """
    filters: list[BehavioralEventFilter] = []

    if not cohort.filters:
        return filters

    properties = cohort.filters.get("properties")
    if not properties:
        return filters

    def traverse_filter_tree(node: Any) -> None:
        if not isinstance(node, dict):
            return

        node_type = node.get("type")
        if node_type in ("AND", "OR"):
            for child in node.get("values", []):
                traverse_filter_tree(child)
            return

        if node_type != "behavioral":
            return

        # Only extract supported behavioral types
        value = node.get("value")
        if value not in SUPPORTED_BEHAVIORAL_TYPES:
            return

        condition_hash = node.get("conditionHash")
        bytecode = node.get("bytecode")
        event_name = node.get("key")

        if not condition_hash or not bytecode or not event_name:
            return

        # Bytecode must be a list with header + version + at least one op
        if not isinstance(bytecode, list) or len(bytecode) <= 2:
            logger.warning(
                "Skipping behavioral filter with invalid bytecode",
                condition_hash=condition_hash,
                bytecode_type=type(bytecode).__name__,
            )
            return

        # event_name must be a string (action IDs are ints and not supported for backfill)
        if not isinstance(event_name, str):
            return

        time_value = node.get("time_value")
        time_interval = node.get("time_interval")

        # Parse time_value: the filter data stores it as a string
        if time_value is not None:
            try:
                time_value = int(time_value)
            except (ValueError, TypeError):
                logger.warning(
                    "Skipping behavioral filter with invalid time_value",
                    condition_hash=condition_hash,
                    time_value=node.get("time_value"),
                )
                return

        # Default to 30 days if time window is missing
        if time_value is None or time_interval is None:
            time_value = 30
            time_interval = "day"

        filters.append(
            BehavioralEventFilter(
                condition_hash=condition_hash,
                bytecode=bytecode,
                cohort_ids=[],  # Populated during deduplication
                event_name=event_name,
                time_value=time_value,
                time_interval=time_interval,
                event_filters=node.get("event_filters"),
            )
        )

    traverse_filter_tree(properties)
    return filters


def compute_backfill_days(filters: list[BehavioralEventFilter]) -> tuple[int, int]:
    """Compute the number of days to backfill from filter time windows.

    Takes the maximum time window across all filters and clamps to MAX_BACKFILL_DAYS.

    Returns:
        Tuple of (clamped_days, unclamped_days).
    """
    if not filters:
        return 0, 0

    max_days = 0
    for f in filters:
        multiplier = TIME_INTERVAL_TO_DAYS.get(f.time_interval, 1)
        filter_days = f.time_value * multiplier
        max_days = max(max_days, filter_days)

    return min(max_days, MAX_BACKFILL_DAYS), max_days


class Command(BaseCommand):
    help = "Backfill precalculated_events table for realtime cohorts with behavioral event filters"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=int,
            required=False,
            help="Team ID to backfill events for. Cannot be used with --team-ids",
        )
        parser.add_argument(
            "--team-ids",
            type=int,
            nargs="+",
            required=False,
            help="List of team IDs to backfill events for. Cannot be used with --team-id",
        )
        parser.add_argument(
            "--cohort-id",
            type=int,
            required=False,
            help="Optional: Specific cohort ID to backfill. Can only be used with --team-id",
        )
        parser.add_argument(
            "--days",
            type=int,
            required=False,
            help=f"Override the backfill time window in days (default: auto-computed from filters, max: {MAX_BACKFILL_DAYS})",
        )
        parser.add_argument(
            "--concurrent-workflows",
            type=int,
            default=5,
            help="Number of concurrent child workflows to run (default: 5)",
        )
        parser.add_argument(
            "--force-reprocess",
            action="store_true",
            default=False,
            help="Skip the already-backfilled check and reprocess all days unconditionally",
        )

    def handle(self, *args, **options):
        team_id = options.get("team_id")
        team_ids_option = options.get("team_ids")
        cohort_id = options.get("cohort_id")
        days_override = options.get("days")
        concurrent_workflows = options["concurrent_workflows"]
        force_reprocess = options["force_reprocess"]

        if team_id and team_ids_option:
            raise CommandError("Cannot use both --team-id and --team-ids. Please use only one.")

        if not team_id and not team_ids_option:
            raise CommandError("Must provide either --team-id or --team-ids")

        if cohort_id and team_ids_option:
            raise CommandError("Cannot use --cohort-id with --team-ids. Use --cohort-id only with --team-id.")

        if days_override is not None and days_override <= 0:
            raise CommandError("--days must be a positive integer")

        if team_id:
            team_ids = [team_id]
        else:
            team_ids = sorted(set(team_ids_option or []))

        self.stdout.write(self.style.SUCCESS(f"Processing {len(team_ids)} team(s): {team_ids}"))

        for current_team_id in team_ids:
            self.stdout.write(self.style.SUCCESS(f"\n=== Processing Team {current_team_id} ==="))

            if cohort_id:
                try:
                    cohorts = [Cohort.objects.get(id=cohort_id, team_id=current_team_id)]
                except Cohort.DoesNotExist:
                    raise CommandError(f"Cohort {cohort_id} not found for team {current_team_id}")
            else:
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

            self.stdout.write(
                self.style.SUCCESS(f"Found {len(cohorts)} cohort(s) to evaluate for team {current_team_id}")
            )

            # Collect and deduplicate filters across all cohorts
            condition_map: dict[str, _DeduplicatedCondition] = {}
            cohort_ids: list[int] = []
            total_original_filters = 0

            for cohort in cohorts:
                if cohort.cohort_type != CohortType.REALTIME:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipping cohort {cohort.id}: not a realtime cohort (type: {cohort.cohort_type})"
                        )
                    )
                    continue

                filters = extract_behavioral_filters(cohort)
                if not filters:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipping cohort {cohort.id}: no behavioral filters with conditionHash and bytecode"
                        )
                    )
                    continue

                cohort_ids.append(cohort.id)
                total_original_filters += len(filters)
                self.stdout.write(self.style.SUCCESS(f"Cohort {cohort.id}: found {len(filters)} behavioral filters"))

                for f in filters:
                    if f.condition_hash not in condition_map:
                        condition_map[f.condition_hash] = _DeduplicatedCondition(
                            bytecode=f.bytecode,
                            event_name=f.event_name,
                            time_value=f.time_value,
                            time_interval=f.time_interval,
                            event_filters=f.event_filters,
                            cohort_ids={cohort.id},
                        )
                        self.stdout.write(f"  + New condition: {f.condition_hash} (event: {f.event_name})")
                    else:
                        condition_map[f.condition_hash].cohort_ids.add(cohort.id)
                        self.stdout.write(f"  = Duplicate condition: {f.condition_hash}")

            if not condition_map:
                self.stdout.write(
                    self.style.WARNING(f"No behavioral filters found across any cohorts for team {current_team_id}")
                )
                continue

            deduplicated_filters = [
                BehavioralEventFilter(
                    condition_hash=condition_hash,
                    bytecode=cond.bytecode,
                    cohort_ids=sorted(cond.cohort_ids),
                    event_name=cond.event_name,
                    time_value=cond.time_value,
                    time_interval=cond.time_interval,
                    event_filters=cond.event_filters,
                )
                for condition_hash, cond in sorted(condition_map.items())
            ]

            cohort_ids = sorted(cohort_ids)

            # Compute effective backfill days
            if days_override is not None:
                effective_days = min(days_override, MAX_BACKFILL_DAYS)
                if days_override > MAX_BACKFILL_DAYS:
                    self.stdout.write(
                        self.style.WARNING(
                            f"--days {days_override} exceeds MAX_BACKFILL_DAYS ({MAX_BACKFILL_DAYS}), clamping to {MAX_BACKFILL_DAYS}"
                        )
                    )
            else:
                effective_days, auto_computed_unclamped = compute_backfill_days(deduplicated_filters)
                if auto_computed_unclamped > MAX_BACKFILL_DAYS:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Auto-computed backfill window ({auto_computed_unclamped} days) exceeds "
                            f"MAX_BACKFILL_DAYS ({MAX_BACKFILL_DAYS}), clamping to {MAX_BACKFILL_DAYS}"
                        )
                    )

            backfill_start = dt.datetime.now(dt.UTC) - dt.timedelta(days=effective_days)

            event_names = sorted({f.event_name for f in deduplicated_filters})

            self.stdout.write(
                self.style.SUCCESS(
                    f"\nDeduplicated {len(deduplicated_filters)} unique conditions across {len(cohort_ids)} cohorts\n"
                    f"  Events: {event_names}\n"
                    f"  Backfill window: {effective_days} days (from {backfill_start.strftime('%Y-%m-%d')} to now)"
                )
            )
            for filter_obj in deduplicated_filters:
                self.stdout.write(
                    f"  - {filter_obj.condition_hash} (event: {filter_obj.event_name}, "
                    f"window: {filter_obj.time_value} {filter_obj.time_interval}s, "
                    f"cohorts: {filter_obj.cohort_ids})"
                )

            self.stdout.write(
                self.style.SUCCESS(
                    f"\nProcessing {len(cohort_ids)} cohorts: reduced {total_original_filters} "
                    f"filters to {len(deduplicated_filters)} unique conditions"
                )
            )

            try:
                workflow_id = self.run_temporal_workflow(
                    team_id=current_team_id,
                    filters=deduplicated_filters,
                    cohort_ids=cohort_ids,
                    effective_days=effective_days,
                    concurrent_workflows=concurrent_workflows,
                    force_reprocess=force_reprocess,
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
                    f"  Backfill window: {effective_days} days\n"
                    f"  Concurrent workflows: {concurrent_workflows}"
                )
            )

    def run_temporal_workflow(
        self,
        team_id: int,
        filters: list[BehavioralEventFilter],
        cohort_ids: list[int],
        effective_days: int,
        concurrent_workflows: int,
        force_reprocess: bool = False,
    ) -> str:
        """Run the Temporal coordinator workflow for the team."""
        import time

        filter_storage_key = store_event_filters(filters, team_id)
        self.stdout.write(
            self.style.SUCCESS(f"Stored {len(filters)} event filters in Redis with key: {filter_storage_key}")
        )

        # TODO(Stage 3): Replace with BackfillPrecalculatedEventsCoordinatorInputs
        # and the actual coordinator workflow once they exist.
        # For now, just store filters and return a placeholder workflow ID.
        workflow_id = f"backfill-precalculated-events-team-{team_id}-{int(time.time())}"

        self.stdout.write(
            self.style.WARNING(
                f"Coordinator workflow not yet implemented. "
                f"Filters stored at: {filter_storage_key} "
                f"(days={effective_days}, concurrent={concurrent_workflows})"
            )
        )

        return workflow_id
