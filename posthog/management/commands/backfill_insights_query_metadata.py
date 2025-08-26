from __future__ import annotations

import math
import time
from datetime import datetime

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

import structlog

from posthog.hogql_queries.query_metadata import InsightQueryMetadata
from posthog.models import Insight

logger = structlog.get_logger(__name__)


def format_duration(seconds: float) -> str:
    """Format duration in seconds to human-readable string."""
    if seconds > 60 * 60:
        return f"{seconds / 3600:.2f} hours"
    elif seconds > 60:
        return f"{seconds / 60:.2f} minutes"
    else:
        return f"{seconds:.2f} seconds"


class Command(BaseCommand):
    help = "Backfill query_metadata for Insight/dashboarditem records"

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=100, help="Number of insights to process in each batch")
        parser.add_argument("--sleep-interval", type=float, default=0.1, help="Sleep time between batches in seconds")
        parser.add_argument("--team-id", type=int, help="Process insights for a specific team only")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run in dry-run mode without making any changes to the database.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed information about the process",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        sleep_interval = options["sleep_interval"]
        team_id = options["team_id"]
        dry_run = options["dry_run"]
        verbose = options["verbose"]

        if dry_run:
            self.stdout.write(self.style.WARNING("Running in dry-run mode - no changes will be made"))
        else:
            self.stdout.write(self.style.SUCCESS("Running in live mode - changes will be made to the database"))

        self.stdout.write(self.style.SUCCESS("Starting query_metadata backfill process"))
        self.stdout.write(
            f"Configuration: batch_size={batch_size}, sleep_interval={sleep_interval}, "
            f"team_id={team_id}, dry_run={dry_run}"
        )

        self.backfill_insights_query_metadata(
            batch_size=batch_size, sleep_interval=sleep_interval, team_id=team_id, dry_run=dry_run, verbose=verbose
        )

    def backfill_insights_query_metadata(
        self,
        batch_size: int,
        sleep_interval: float,
        team_id: int | None = None,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> None:
        """
        Backfill query_metadata for insights that don't have it.

        Processes insights in small batches to minimize memory usage.
        Uses proper row locking to prevent race conditions.
        """
        # Build base query
        base_query = Insight.objects_including_soft_deleted.filter(
            Q(query_metadata__isnull=True) | Q(query_metadata={})
        )

        if team_id:
            base_query = base_query.filter(team_id=team_id)

        # Get total count for estimates
        total_insights = base_query.count()
        total_updated = 0
        total_processed = 0
        start_time = time.time()

        self.stdout.write(f"Found {total_insights} insights to update")

        if total_insights == 0:
            self.stdout.write(self.style.SUCCESS("No insights to update. Exiting."))
            return

        if dry_run:
            estimated_batches = math.ceil(total_insights / batch_size)
            estimated_time = (estimated_batches * sleep_interval) + (total_insights * 0.1)  # rough estimate
            self.stdout.write(
                f"DRY RUN: Would process {total_insights} insights in {estimated_batches} batches "
                f"in approximately {format_duration(estimated_time)}"
            )

        # Process in batches to minimize memory usage
        while True:
            batch_start_time = time.time()

            # Process one batch at a time
            with transaction.atomic():
                # Get a batch of insights WITH ROW LOCKING
                # This ensures no one else can modify these rows while we're processing them
                insights = list(
                    base_query.order_by("id")
                    .select_for_update(skip_locked=True, of=("self",))  # Add row locking
                    .select_related("team")
                    .only("id", "query", "query_metadata", "team")[:batch_size]
                )

                if not insights:
                    # If we got no insights, we're done
                    break

                batch_updated = 0
                insights_to_update = []

                for insight in insights:
                    # Skip insights that already have metadata
                    if insight.query_metadata and insight.query_metadata != {}:
                        continue

                    # Generate metadata
                    try:
                        insight.generate_query_metadata()
                        batch_updated += 1
                        if verbose:
                            self.stdout.write(f"Insight {insight.id}: Generated query metadata")
                    except Exception as e:
                        logger.exception(f"Failed to generate metadata for insight {insight.id}: {e}")
                        # store an empty metadata to avoid reprocessing, with a specific datetime to know which ones failed via this command (hacky, I know)
                        failed_datetime = datetime(2025, 1, 1, 0, 0, 0)
                        insight.query_metadata = InsightQueryMetadata(events=[], updated_at=failed_datetime).model_dump(
                            exclude_none=True, mode="json"
                        )

                    insights_to_update.append(insight)

                # Update all modified insights in this batch
                if insights_to_update and not dry_run:
                    Insight.objects_including_soft_deleted.bulk_update(insights_to_update, ["query_metadata"])

                total_updated += batch_updated
                total_processed += len(insights)

                batch_duration = time.time() - batch_start_time

                # Report progress
                percent_complete = (total_processed / total_insights) * 100 if total_insights > 0 else 100
                elapsed_time = time.time() - start_time
                est_remaining = (
                    (elapsed_time / total_processed) * (total_insights - total_processed) if total_processed > 0 else 0
                )

                self.stdout.write(
                    f"Batch: Processed {len(insights)} insights, updated {batch_updated} in {batch_duration:.2f}s "
                    f"({len(insights) / batch_duration:.1f} insights/sec)"
                )
                self.stdout.write(
                    f"Progress: {percent_complete:.1f}% ({total_processed}/{total_insights}) | "
                    f"Elapsed: {format_duration(elapsed_time)} | "
                    f"Estimated remaining: {format_duration(est_remaining)}"
                )

            # Sleep between batches
            if sleep_interval > 0:
                time.sleep(sleep_interval)

        # Check if we processed all insights
        if total_processed < total_insights:
            self.stdout.write(
                self.style.WARNING(
                    f"Note: Only processed {total_processed} out of {total_insights} insights. "
                    f"The remaining {total_insights - total_processed} insights may have been locked "
                    f"by other processes."
                )
            )

        # Final summary
        total_duration = time.time() - start_time
        avg_speed = total_processed / total_duration if total_duration > 0 else 0

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"DRY RUN COMPLETE: Would have updated {total_updated} insights out of {total_processed} processed "
                    f"in {format_duration(total_duration)} ({avg_speed:.1f} insights/sec)"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully updated {total_updated} insights out of {total_processed} processed "
                    f"in {format_duration(total_duration)} ({avg_speed:.1f} insights/sec)"
                )
            )
