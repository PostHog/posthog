import datetime as dt

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

import structlog

from products.data_modeling.backend.models.data_modeling_job import (
    DataModelingJob,
    DataModelingJobEngine,
    DataModelingJobStatus,
)

logger = structlog.get_logger(__name__)

# A duckgres shadow job can legitimately stay RUNNING far longer than a single 20-minute
# activity attempt: in duckgres_only mode the activity retries up to 3 times (maximum_attempts=3),
# each with its own 20-minute start_to_close_timeout, so the worst-case in-flight window is
# ~3 × 20min + backoffs ≈ 65 minutes. The default cutoff sits well above that so the reaper never
# races a live job; only lower it via --minutes if you know nothing is in flight for those jobs.
DEFAULT_STALE_MINUTES = 6 * 60

REAP_ERROR = "Reaped: duckgres shadow job exceeded activity timeout without finalizing"


class Command(BaseCommand):
    help = "Mark orphaned duckgres shadow DataModelingJobs (stuck in RUNNING past the activity timeout) as FAILED"

    def add_arguments(self, parser):
        parser.add_argument(
            "--minutes",
            type=int,
            default=DEFAULT_STALE_MINUTES,
            help=f"Minimum age in minutes before a RUNNING duckgres job is treated as orphaned "
            f"(default: {DEFAULT_STALE_MINUTES}, i.e. 6h — safely above the worst-case retry window)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Preview orphaned jobs without modifying them",
        )

    def handle(self, **options):
        cutoff = timezone.now() - dt.timedelta(minutes=options["minutes"])
        orphaned = DataModelingJob.objects.filter(
            engine=DataModelingJobEngine.DUCKGRES,
            status=DataModelingJobStatus.RUNNING,
            created_at__lt=cutoff,
        )

        count = orphaned.count()
        if count == 0:
            self.stdout.write("No orphaned duckgres shadow jobs found")
            return

        self.stdout.write(f"Found {count} orphaned duckgres shadow job(s) created before {cutoff.isoformat()}")
        for job_id, team_id, created_at in orphaned.values_list("id", "team_id", "created_at")[:50]:
            self.stdout.write(f"  job={job_id} team={team_id} created_at={created_at.isoformat()}")
        if count > 50:
            self.stdout.write(f"  ... and {count - 50} more")

        if options["dry_run"]:
            self.stdout.write(f"DRY RUN: would mark {count} job(s) as FAILED")
            return

        if not settings.TEST:
            confirm = input(f"\n\tWill mark {count} job(s) as FAILED. Proceed? (y/n) ")
            if confirm.strip().lower() != "y":
                self.stdout.write("Aborting")
                return

        updated = orphaned.update(
            status=DataModelingJobStatus.FAILED,
            rows_materialized=0,
            error=REAP_ERROR,
            last_run_at=timezone.now(),
        )
        logger.info("reaped_orphaned_duckgres_jobs", count=updated)
        self.stdout.write(f"Marked {updated} orphaned duckgres shadow job(s) as FAILED")
