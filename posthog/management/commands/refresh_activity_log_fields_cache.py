from django.core.management.base import BaseCommand

from posthog.api.advanced_activity_logs.field_discovery import SMALL_ORG_THRESHOLD
from posthog.tasks.tasks import refresh_activity_log_fields_cache


class Command(BaseCommand):
    help = "Refresh activity log fields cache for large organizations"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Show what would be processed without running")

    def handle(self, *args, **options):
        if options["dry_run"]:
            from django.db.models import Count

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
            for org in large_orgs:
                self.stdout.write(f"  - {org.name} (id={org.id}) - {org.activity_count:,} records")
        else:
            self.stdout.write("Starting activity log fields cache refresh...")
            refresh_activity_log_fields_cache()
            self.stdout.write("Cache refresh completed.")
