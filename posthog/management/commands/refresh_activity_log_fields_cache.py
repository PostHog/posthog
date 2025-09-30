from django.core.management.base import BaseCommand

from posthog.api.advanced_activity_logs.constants import SMALL_ORG_THRESHOLD
from posthog.tasks.tasks import refresh_activity_log_fields_cache


class Command(BaseCommand):
    help = "Refresh activity log fields cache for large organizations"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Show what would be processed without running")
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete existing cache and rebuild from scratch (uses 10% sampling for full rebuild)",
        )
        parser.add_argument(
            "--hours-back",
            type=int,
            default=14,
            help="Number of hours to look back when not using --flush (default: 14 = 12h + 2h buffer)",
        )

    def handle(self, *args, **options):
        if options["dry_run"]:
            from datetime import timedelta

            from django.db.models import Count
            from django.utils import timezone

            from posthog.models import Organization
            from posthog.models.activity_logging.activity_log import ActivityLog

            # Query ActivityLog directly to get organizations with large activity counts
            large_org_data = (
                ActivityLog.objects.values("organization_id")
                .annotate(activity_count=Count("id"))
                .filter(activity_count__gt=SMALL_ORG_THRESHOLD)
                .order_by("-activity_count")
            )

            # Get the actual Organization objects
            large_org_ids = [data["organization_id"] for data in large_org_data if data["organization_id"]]
            large_orgs = list(Organization.objects.filter(id__in=large_org_ids))

            # Create mapping for activity counts
            activity_counts = {data["organization_id"]: data["activity_count"] for data in large_org_data}
            for org in large_orgs:
                org.activity_count = activity_counts.get(org.id, 0)

            self.stdout.write(f"Would process {len(large_orgs)} organizations:")

            if options["flush"]:
                self.stdout.write("Mode: FLUSH - Delete existing cache and rebuild from scratch with 10% sampling")
                for org in large_orgs:
                    self.stdout.write(f"  - {org.name} (id={org.id}) - {org.activity_count:,} total records")
            else:
                cutoff = timezone.now() - timedelta(hours=options["hours_back"])
                self.stdout.write(f"Mode: INCREMENTAL - Process last {options['hours_back']} hours with 100% coverage")
                self.stdout.write(f"Cutoff time: {cutoff}")

                for org in large_orgs:
                    recent_count = ActivityLog.objects.filter(
                        organization_id=org.id, created_at__gte=cutoff, detail__isnull=False
                    ).count()
                    self.stdout.write(
                        f"  - {org.name} (id={org.id}) - {recent_count:,} records from last {options['hours_back']}h"
                    )
        else:
            mode = (
                "FLUSH mode"
                if options["flush"]
                else f"INCREMENTAL mode (last {options['hours_back']}h with 100% coverage)"
            )
            self.stdout.write(f"Starting activity log fields cache refresh in {mode}...")

            refresh_activity_log_fields_cache(flush=options["flush"], hours_back=options["hours_back"])

            self.stdout.write("Cache refresh completed.")
