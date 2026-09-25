import time

from django.core.management.base import BaseCommand
from django.core.paginator import Paginator
from django.test import RequestFactory

import structlog

from products.workflows.backend.api.hog_flow import HogFlowSerializer
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Refresh HogFlows (all statuses) by re-saving them to trigger reload on workers"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id", type=int, help="Team ID to refresh HogFlows for (if not provided, processes all teams)"
        )
        parser.add_argument(
            "--hog-flow-id",
            type=str,
            help="Specific HogFlow ID to refresh (if provided, only this flow is processed)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be re-saved, and which flows no longer validate, without saving.",
        )
        parser.add_argument(
            "--page-size",
            type=int,
            default=1000,
            help="Number of flows to process per page (default: 1000)",
        )

    def handle(self, *args, **options):
        start_time = time.time()
        total_processed = 0
        total_updated = 0
        error_count = 0

        team_id = options.get("team_id")
        hog_flow_id = options.get("hog_flow_id")
        page_size = options.get("page_size", 1000)
        dry_run: bool = options.get("dry_run", False)

        self.stdout.write("Starting HogFlow refresh..." + (" (dry run, nothing is saved)" if dry_run else ""))

        queryset = HogFlow.objects.select_related("team")

        if hog_flow_id:
            queryset = queryset.filter(id=hog_flow_id)
            self.stdout.write(f"Processing single HogFlow: {hog_flow_id}")
        elif team_id:
            queryset = queryset.filter(team_id=team_id)
            self.stdout.write(f"Processing HogFlows for team: {team_id}")
        else:
            self.stdout.write("Processing HogFlows for all teams")

        total_count = queryset.count()
        self.stdout.write(f"Found {total_count} HogFlows to process")

        if total_count == 0:
            self.stdout.write(self.style.WARNING("No HogFlows found matching criteria"))
            return

        paginator = Paginator(queryset.order_by("id"), page_size)

        for page_num in paginator.page_range:
            page = paginator.page(page_num)

            self.stdout.write(f"Processing page {page_num}/{paginator.num_pages} ({len(page.object_list)} flows)...")

            for hog_flow in page.object_list:
                try:
                    total_processed += 1

                    # Create a mock request context for the serializer
                    request = RequestFactory().post("/")
                    if hog_flow.created_by:
                        request.user = hog_flow.created_by

                    def get_team_func(flow=hog_flow):
                        return flow.team

                    serializer_context = {
                        "request": request,
                        "team_id": hog_flow.team_id,
                        "get_team": get_team_func,
                    }

                    # Get the current data from the HogFlow
                    data = {
                        "name": hog_flow.name,
                        "description": hog_flow.description,
                        "status": hog_flow.status,
                        "trigger": hog_flow.trigger,
                        "trigger_masking": hog_flow.trigger_masking,
                        "conversion": hog_flow.conversion,
                        "exit_condition": hog_flow.exit_condition,
                        "edges": hog_flow.edges,
                        "actions": hog_flow.actions,
                        "variables": hog_flow.variables,
                    }

                    # Process through serializer to regenerate bytecode
                    serializer = HogFlowSerializer(
                        instance=hog_flow, data=data, context=serializer_context, partial=True
                    )

                    if serializer.is_valid():
                        if not dry_run:
                            serializer.save()
                        total_updated += 1
                        logger.info(
                            "Would refresh HogFlow" if dry_run else "Successfully refreshed HogFlow",
                            hog_flow_id=str(hog_flow.id),
                            team_id=hog_flow.team_id,
                            status=hog_flow.status,
                            name=hog_flow.name,
                            version=hog_flow.version,
                            dry_run=dry_run,
                        )
                    else:
                        # A workflow that no longer validates cannot be re-saved, so it keeps whatever
                        # it was last compiled against. Name it: the owner has to fix it or turn it off.
                        self.stdout.write(
                            self.style.WARNING(
                                f"Does not validate: team {hog_flow.team_id}, workflow {hog_flow.id} ({hog_flow.name})"
                            )
                        )
                        raise Exception(f"Serializer validation failed: {serializer.errors}")

                except Exception as e:
                    error_count += 1
                    logger.error(
                        "Error refreshing HogFlow",
                        hog_flow_id=str(hog_flow.id),
                        team_id=hog_flow.team_id,
                        status=hog_flow.status,
                        name=hog_flow.name,
                        error=str(e),
                        exc_info=True,
                    )
                    self.stdout.write(self.style.ERROR(f"Error processing flow {hog_flow.id}: {str(e)}"))

        # Output summary
        duration = time.time() - start_time
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{'Dry run' if dry_run else 'Refresh'} completed in {duration:.2f}s.\n"
                f"Processed: {total_processed}\n"
                f"{'Would update' if dry_run else 'Updated'}: {total_updated}\n"
                f"Errors: {error_count}"
            )
        )

        if error_count > 0:
            self.stdout.write(self.style.WARNING(f"Check logs for details on {error_count} errors encountered"))
