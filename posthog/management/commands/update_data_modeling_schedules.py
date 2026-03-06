import logging
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import structlog
import temporalio

from products.data_warehouse.backend.data_load.saved_query_service import sync_saved_query_workflow
from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Updates Temporal schedules for data modeling saved queries to spread them around midnight UTC"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-ids",
            default=None,
            type=str,
            help="Comma separated list of team IDs to filter by",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Only show what would be updated without making changes",
        )

    def handle(self, **options):
        logger.setLevel(logging.INFO)

        queryset = DataWarehouseSavedQuery.objects.filter(
            deleted=False,
            sync_frequency_interval__gte=timedelta(hours=24),
        )

        if options.get("team_ids") is not None:
            try:
                team_ids = [int(tid) for tid in options["team_ids"].split(",")]
            except ValueError:
                raise CommandError("team_ids must be a comma separated list of team IDs")
            queryset = queryset.filter(team_id__in=team_ids)

        saved_queries = list(queryset)

        if len(saved_queries) == 0:
            raise CommandError("No saved queries found matching filters")

        logger.info(f"Found {len(saved_queries)} saved queries to update")

        if options["dry_run"]:
            for sq in saved_queries:
                logger.info("Would update schedule", saved_query_id=str(sq.id), team_id=sq.team_id)
            return

        if not settings.TEST:
            confirm = input(f"\n\tWill update schedules for {len(saved_queries)} saved queries. Proceed? (y/n) ")
            if confirm.strip().lower() != "y":
                logger.info("Aborting")
                return

        updated = 0
        failed = 0
        not_found_ids: list[str] = []

        for num, saved_query in enumerate(saved_queries):
            try:
                sync_saved_query_workflow(saved_query, create=False)
                updated += 1
            except temporalio.service.RPCError as e:
                if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
                    not_found_ids.append(str(saved_query.id))
                    logger.warning("Schedule not found in Temporal", saved_query_id=str(saved_query.id))
                else:
                    failed += 1
                    logger.exception("Error updating schedule", saved_query_id=str(saved_query.id))
            except Exception:
                failed += 1
                logger.exception("Error updating schedule", saved_query_id=str(saved_query.id))

            if (num + 1) % 100 == 0:
                logger.info(f"Progress: {num + 1}/{len(saved_queries)}")

        logger.info(f"Done! Updated: {updated}, Failed: {failed}, Not found: {len(not_found_ids)}")

        if not_found_ids:
            logger.info("Saved queries with no Temporal schedule (orphaned):\n" + "\n".join(not_found_ids))
