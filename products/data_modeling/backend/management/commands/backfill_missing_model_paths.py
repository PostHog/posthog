import time
import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import structlog

from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_warehouse.backend.models.modeling import DataWarehouseModelPath

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = (
        "Creates missing DataWarehouseModelPath records for materialized saved queries that have schedules but no paths"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-ids",
            default=None,
            type=str,
            help="Comma separated list of team IDs to filter by",
        )
        parser.add_argument(
            "--batch-size",
            default=50,
            type=int,
            help="Number of saved queries to process per batch (default: 50)",
        )
        parser.add_argument(
            "--batch-delay",
            default=1.0,
            type=float,
            help="Seconds to wait between batches (default: 1.0)",
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
            sync_frequency_interval__isnull=False,
        ).exclude(deleted=True)

        if options.get("team_ids") is not None:
            try:
                team_ids = [int(tid) for tid in options["team_ids"].split(",")]
            except ValueError:
                raise CommandError("team-ids must be a comma separated list of team IDs")
            queryset = queryset.filter(team_id__in=team_ids)

        saved_queries = list(queryset.order_by("team_id", "id"))

        if not saved_queries:
            logger.info("No materialized saved queries found matching filters")
            return

        logger.info(f"Checking {len(saved_queries)} materialized saved queries for missing model paths")

        sq_ids_with_paths = set(
            DataWarehouseModelPath.objects.filter(saved_query__in=saved_queries).values_list(
                "saved_query_id", flat=True
            )
        )
        missing = [sq for sq in saved_queries if sq.id not in sq_ids_with_paths]

        logger.info(f"Found {len(missing)} saved queries with no model paths (out of {len(saved_queries)} total)")

        if not missing:
            logger.info("All saved queries have model paths, nothing to do")
            return

        if options["dry_run"]:
            for sq in missing:
                logger.info("Would create model paths", saved_query_id=str(sq.id), team_id=sq.team_id, name=sq.name)
            return

        if not settings.TEST:
            confirm = input(f"\n\tWill create model paths for {len(missing)} saved queries. Proceed? (y/n) ")
            if confirm.strip().lower() != "y":
                logger.info("Aborting")
                return

        batch_size = options["batch_size"]
        batch_delay = options["batch_delay"]
        created = 0
        failed = 0

        for batch_start in range(0, len(missing), batch_size):
            batch = missing[batch_start : batch_start + batch_size]
            batch_num = batch_start // batch_size + 1
            total_batches = (len(missing) + batch_size - 1) // batch_size

            logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} queries)")

            for sq in batch:
                try:
                    sq.setup_model_paths()
                    created += 1
                    logger.info(
                        "Created model paths",
                        saved_query_id=str(sq.id),
                        team_id=sq.team_id,
                        name=sq.name,
                    )
                except Exception:
                    failed += 1
                    logger.exception(
                        "Error creating model paths",
                        saved_query_id=str(sq.id),
                        team_id=sq.team_id,
                    )

            if batch_start + batch_size < len(missing):
                logger.info(f"Sleeping {batch_delay}s between batches")
                time.sleep(batch_delay)

        logger.info(f"Done! Created: {created}, Failed: {failed}, Total checked: {len(saved_queries)}")
