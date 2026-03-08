import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import structlog

from products.data_warehouse.backend.data_load.saved_query_service import (
    saved_query_workflow_exists,
    sync_saved_query_workflow,
)
from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Creates missing Temporal schedules for materialized saved queries that should be refreshing"

    def add_arguments(self, parser):
        parser.add_argument(
            "--saved-query-ids",
            default=None,
            type=str,
            help="Comma separated list of saved query UUIDs to check",
        )
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
            help="Only show what would be created without making changes",
        )

    def handle(self, **options):
        logger.setLevel(logging.INFO)

        queryset = DataWarehouseSavedQuery.objects.filter(
            deleted=False,
            sync_frequency_interval__isnull=False,
        )

        if options.get("saved_query_ids") is not None:
            try:
                sq_ids = [uid.strip() for uid in options["saved_query_ids"].split(",")]
            except ValueError:
                raise CommandError("saved-query-ids must be a comma separated list of UUIDs")
            queryset = queryset.filter(id__in=sq_ids)

        if options.get("team_ids") is not None:
            try:
                team_ids = [int(tid) for tid in options["team_ids"].split(",")]
            except ValueError:
                raise CommandError("team-ids must be a comma separated list of team IDs")
            queryset = queryset.filter(team_id__in=team_ids)

        saved_queries = list(queryset)

        if len(saved_queries) == 0:
            raise CommandError("No materialized saved queries found matching filters")

        logger.info(f"Found {len(saved_queries)} materialized saved queries to check")

        missing = []
        already_exists = 0

        for num, sq in enumerate(saved_queries):
            if saved_query_workflow_exists(sq):
                already_exists += 1
            else:
                missing.append(sq)
                logger.info(
                    "Missing schedule",
                    saved_query_id=str(sq.id),
                    team_id=sq.team_id,
                    name=sq.name,
                )

            if (num + 1) % 100 == 0:
                logger.info(f"Check progress: {num + 1}/{len(saved_queries)}")

        logger.info(f"Check complete: {len(missing)} missing, {already_exists} already exist")

        if not missing:
            logger.info("All schedules exist, nothing to do")
            return

        if options["dry_run"]:
            logger.info("Dry run, not creating schedules")
            return

        if not settings.TEST:
            confirm = input(f"\n\tWill create schedules for {len(missing)} saved queries. Proceed? (y/n) ")
            if confirm.strip().lower() != "y":
                logger.info("Aborting")
                return

        created = 0
        failed = 0

        for num, sq in enumerate(missing):
            try:
                sync_saved_query_workflow(sq, create=True)
                created += 1
                logger.info("Created schedule", saved_query_id=str(sq.id), team_id=sq.team_id)
            except Exception:
                failed += 1
                logger.exception("Error creating schedule", saved_query_id=str(sq.id))

            if (num + 1) % 100 == 0:
                logger.info(f"Create progress: {num + 1}/{len(missing)}")

        logger.info(f"Done! Created: {created}, Failed: {failed}, Already existed: {already_exists}")
