import time
import logging
from typing import Final

from django.core.management.base import BaseCommand
from django.core.paginator import Paginator

from posthog.models.hog_flow.hog_flow import HogFlow
from posthog.models.hog_flow.hog_flow_revision import HogFlowRevision

logger = logging.getLogger(__name__)

CONTENT_FIELDS: Final = (
    "name",
    "description",
    "trigger",
    "trigger_masking",
    "conversion",
    "exit_condition",
    "edges",
    "actions",
    "abort_action",
    "variables",
    "billable_action_types",
)


class Command(BaseCommand):
    help = "Create v1 active revisions for existing HogFlows that don't have one yet, and set active_revision FK"

    def add_arguments(self, parser):
        parser.add_argument(
            "--page-size",
            type=int,
            default=500,
            help="Number of HogFlows to process per page (default: 500)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run without making any changes to the database",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            help="Only process HogFlows for this team",
        )

    def handle(self, *args, **options):
        start_time = time.time()
        page_size = options["page_size"]
        dry_run = options["dry_run"]
        team_id = options.get("team_id")

        if dry_run:
            self.stdout.write(self.style.WARNING("Running in DRY RUN mode - no changes will be made"))

        queryset = HogFlow.objects.filter(active_revision__isnull=True)
        if team_id:
            queryset = queryset.filter(team_id=team_id)
            self.stdout.write(f"Processing HogFlows for team: {team_id}")

        total_count = queryset.count()
        self.stdout.write(f"Found {total_count} HogFlows without active revision")

        if total_count == 0:
            self.stdout.write(self.style.SUCCESS("Nothing to backfill"))
            return

        paginator = Paginator(queryset.order_by("id"), page_size)
        created_count = 0
        error_count = 0

        for page_num in paginator.page_range:
            page = paginator.page(page_num)
            self.stdout.write(f"Processing page {page_num}/{paginator.num_pages} ({len(page.object_list)} flows)...")

            for hog_flow in page.object_list:
                try:
                    if dry_run:
                        created_count += 1
                        continue

                    revision = HogFlowRevision(
                        hog_flow=hog_flow,
                        team_id=hog_flow.team_id,
                        version=hog_flow.version,
                        status=HogFlowRevision.State.ACTIVE,
                    )
                    for field in CONTENT_FIELDS:
                        setattr(revision, field, getattr(hog_flow, field))
                    revision.save()

                    # Use .update() to avoid triggering post_save signal
                    HogFlow.objects.filter(pk=hog_flow.pk).update(active_revision=revision)
                    created_count += 1
                except Exception as e:
                    error_count += 1
                    logger.error(
                        f"Error creating revision for HogFlow id={hog_flow.id}, team_id={hog_flow.team_id}: {e}",
                        exc_info=True,
                    )

        duration = time.time() - start_time
        prefix = "DRY RUN: Would have created" if dry_run else "Created"
        self.stdout.write(
            self.style.SUCCESS(
                f"\nBackfill completed in {duration:.2f}s.\n"
                f"Processed: {total_count}\n"
                f"{prefix}: {created_count} revisions\n"
                f"Errors: {error_count}"
            )
        )

        if error_count > 0:
            self.stdout.write(self.style.WARNING(f"Check logs for details on {error_count} errors encountered"))
