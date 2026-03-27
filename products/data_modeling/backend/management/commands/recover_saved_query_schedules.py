"""
Management command to recover saved query schedules affected by a production bug.

This command:
1. Finds saved queries with specific error messages and fields that indicate they were affected by INC-688 bug
2. Groups them by team_id and processes one team at a team to avoid thundering herd
3. For each query, checks if a Temporal schedule exists:
   - If exists: retrieves the interval, updates sync_frequency_interval, and unpauses
   - If not exists: logs for manual handling

Usage:
    # Dry run for unmanaged queries (default)
    python manage.py recover_saved_query_schedules --team-id 2 --dry-run

    # Dry run for managed viewset queries
    python manage.py recover_saved_query_schedules --team-id 2 --managed-viewset

    # Live run
    python manage.py recover_saved_query_schedules --team-id 2

    # Limit number of queries to process (for gradual recovery)
    python manage.py recover_saved_query_schedules --limit 10

    # Limit number of queries to those created after date
    python manage.py recover_saved_query_schedules --created-after '2025-10-01'
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count, OuterRef, Q, Subquery

from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.schedule import describe_schedule, schedule_exists, unpause_schedule

from products.data_warehouse.backend.models import DataWarehouseSavedQuery
from products.data_warehouse.backend.models.data_modeling_job import DataModelingJob

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Recover saved query schedules affected by production bug"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=int,
            help="Process only this team. If not provided, processes the team with most affected queries.",
        )
        parser.add_argument(
            "--managed-viewset",
            action="store_true",
            default=False,
            help="Process managed viewset queries instead of unmanaged queries.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Preview changes without making them.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit the number of queries to process (for gradual recovery).",
        )
        parser.add_argument(
            "--created-after",
            type=str,
            default="2025-10-01",
            help="Only process queries created after this date (YYYY-MM-DD). Default: 2025-10-01",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run = options["dry_run"]
        team_id = options["team_id"]
        managed_viewset = options["managed_viewset"]
        limit = options["limit"]
        created_after = options["created_after"]

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"Saved Query Schedule Recovery - {'DRY_RUN' if dry_run else 'LIVE'}")
        self.stdout.write(f"Query type: {'Managed Viewsets' if managed_viewset else 'Unmanaged Queries'}")
        self.stdout.write(f"{'=' * 60}\n")

        # build the base queryset for affected queries
        base_qs = self._get_affected_queries_queryset(managed_viewset, created_after)
        # report on all affected queries grouped by team
        self._report_affected_queries_by_team(base_qs)
        # determine which team to process
        if team_id:
            target_team_id = team_id
        else:
            target_team_id = self._get_team_with_most_affected_queries(base_qs)
            if target_team_id is None:
                self.stdout.write(self.style.SUCCESS("\nNo affected queries found. Nothing to do."))
                return
        self.stdout.write(f"\nProcessing team_id={target_team_id}")
        # get queries for the target team
        queries = base_qs.filter(team_id=target_team_id).order_by("created_at")
        if limit:
            queries = queries[:limit]
            self.stdout.write(f"Limited to {limit} queries")
        queries = list(queries)
        self.stdout.write(f"Found {len(queries)} affected queries for team_id={target_team_id}\n")
        if not queries:
            self.stdout.write(self.style.SUCCESS("No queries to process for this team."))
            return
        # connect to temporal
        temporal = sync_connect()
        stats = {
            "recovered": 0,
            "no_schedule": 0,
            "already_has_interval": 0,
            "errors": 0,
        }
        for i, query in enumerate(queries, 1):
            self.stdout.write(f"\n[{i}/{len(queries)}] Processing saved_query id={query.id}")
            self.stdout.write(f"  name: {query.name}")
            self.stdout.write(f"  team_id: {query.team_id}")
            self.stdout.write(f"  is_materialized: {query.is_materialized}")
            self.stdout.write(f"  table_id: {query.table_id}")
            self.stdout.write(f"  sync_frequency_interval: {query.sync_frequency_interval}")
            latest_job_error = getattr(query, "latest_job_error", None)
            self.stdout.write(f"  latest_job_error: {latest_job_error[:100] if latest_job_error else None}...")
            # skip if already has sync_frequency_interval set (idempotency)
            if query.sync_frequency_interval is not None:
                self.stdout.write(
                    self.style.WARNING("  -> SKIP: sync_frequency_interval already set (already recovered)")
                )
                stats["already_has_interval"] += 1
                continue
            try:
                self._process_query(temporal, query, dry_run, stats)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  -> ERROR: {e}"))
                stats["errors"] += 1
                logger.exception(f"Error processing saved_query id={query.id}")
        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write("SUMMARY")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"Total processed: {len(queries)}")
        self.stdout.write(f"Recovered: {stats['recovered']}")
        self.stdout.write(f"No schedule (needs manual handling): {stats['no_schedule']}")
        self.stdout.write(f"Already had interval (skipped): {stats['already_has_interval']}")
        self.stdout.write(f"Errors: {stats['errors']}")
        if dry_run:
            self.stdout.write(
                self.style.WARNING("\nThis was a DRY RUN. No changes were made. Remove --dry-run to apply changes.")
            )

    def _get_affected_queries_queryset(self, managed_viewset: bool, created_after: str):
        """Build queryset for affected queries based on the bug conditions.

        Uses the error field from the latest DataModelingJob for each saved query,
        which is more reliable than the saved query's latest_error field.
        """
        # Parse the date string to a timezone-aware datetime
        created_after_dt = datetime.strptime(created_after, "%Y-%m-%d").replace(tzinfo=UTC)

        latest_job_error = (
            DataModelingJob.objects.filter(saved_query=OuterRef("pk")).order_by("-created_at").values("error")[:1]
        )
        qs = DataWarehouseSavedQuery.objects.annotate(latest_job_error=Subquery(latest_job_error)).filter(
            deleted=False,
            created_at__gt=created_after_dt,
            sync_frequency_interval__isnull=True,  # this is a symptom of the bug
        )
        error_conditions = Q(latest_job_error__icontains="Query returned no results") | Q(
            latest_job_error__icontains="You cannot call this from an async context"
        )
        qs = qs.filter(error_conditions)
        if managed_viewset:
            qs = qs.filter(managed_viewset_id__isnull=False)
        else:
            qs = qs.filter(managed_viewset_id__isnull=True)
        return qs

    def _report_affected_queries_by_team(self, base_qs):
        """Report affected queries grouped by team."""
        team_counts = base_qs.values("team_id").annotate(count=Count("id")).order_by("-count")
        self.stdout.write("Affected queries by team:")
        self.stdout.write("-" * 40)
        for entry in team_counts[:20]:  # top 20
            self.stdout.write(f"  team_id={entry['team_id']}: {entry['count']} queries")
        total = sum(entry["count"] for entry in team_counts)
        self.stdout.write(f"\nTotal affected queries: {total}")

    def _get_team_with_most_affected_queries(self, base_qs) -> int | None:
        """Return the team_id with the most affected queries."""
        result = base_qs.values("team_id").annotate(count=Count("id")).order_by("-count").first()
        return result["team_id"] if result else None

    def _process_query(self, temporal, query: DataWarehouseSavedQuery, dry_run: bool, stats: dict):
        """Process a single saved query - check schedule and recover if possible."""
        schedule_id = str(query.id)
        # check if schedule exists
        if not schedule_exists(temporal, schedule_id):
            self.stdout.write(self.style.WARNING("  -> NO SCHEDULE EXISTS"))
            self.stdout.write("     Manual handling needed:")
            self.stdout.write(f"       saved_query_id: {query.id}")
            self.stdout.write(f"       team_id: {query.team_id}")
            self.stdout.write(f"       name: {query.name}")
            self.stdout.write(f"       is_materialized: {query.is_materialized}")
            self.stdout.write(f"       table_id: {query.table_id}")
            stats["no_schedule"] += 1
            return
        schedule_desc = describe_schedule(temporal, schedule_id)
        # Get the interval from the schedule
        if not schedule_desc.schedule.spec.intervals:
            self.stdout.write(
                self.style.WARNING(
                    "  -> Schedule exists but has no intervals configured. 'Paused' is likely the correct state."
                )
            )
            stats["no_schedule"] += 1
            return
        interval: timedelta = schedule_desc.schedule.spec.intervals[0].every
        is_paused = schedule_desc.schedule.state.paused
        self.stdout.write("  -> Schedule exists:")
        self.stdout.write(f"     interval: {interval}")
        self.stdout.write(f"     paused: {is_paused}")
        if dry_run:
            self.stdout.write(self.style.WARNING("  -> DRY RUN: Would update sync_frequency_interval and unpause"))
            stats["recovered"] += 1
            return
        # update sync_frequency_interval on the saved query
        with transaction.atomic():
            # re-fetch with select_for_update to prevent race conditions
            query_to_update = DataWarehouseSavedQuery.objects.select_for_update().get(id=query.id)
            # double-check it hasn't been updated by another process
            if query_to_update.sync_frequency_interval is not None:
                self.stdout.write(self.style.WARNING("  -> SKIP: sync_frequency_interval was set by another process"))
                stats["already_has_interval"] += 1
                return
            # update only the sync_frequency_interval field
            query_to_update.sync_frequency_interval = interval
            query_to_update.save(update_fields=["sync_frequency_interval"])
            self.stdout.write(f"  -> Updated sync_frequency_interval to {interval}")
        # unpause the schedule if it's paused
        if is_paused:
            unpause_schedule(
                temporal,
                schedule_id=schedule_id,
                note="Recovered by recover_saved_query_schedules management command",
            )
            self.stdout.write(self.style.SUCCESS("  -> Unpaused schedule"))
        else:
            self.stdout.write("  -> Schedule was not paused, no unpause needed")
        stats["recovered"] += 1
