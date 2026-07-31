import logging
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

import structlog

from products.data_warehouse.backend.logic.data_load.service import (
    bulk_update_external_data_job_schedules,
    sync_cdc_extraction_schedule,
)
from products.warehouse_sources.backend.facade.models import ExternalDataSchema

logger = structlog.get_logger(__name__)

SYNC_FREQUENCY_FLOOR = timedelta(minutes=5)


class Command(BaseCommand):
    help = (
        "Bump every external data schema syncing faster than the 5-minute floor to 5 minutes, "
        "then re-issue the affected Temporal schedules (per-schema sync schedules and, for CDC "
        "sources, the extraction schedule)"
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report the schemas that would be updated without changing anything",
        )

    def handle(self, **options: Any) -> None:
        logger.setLevel(logging.INFO)
        dry_run: bool = options["dry_run"]

        # Soft-deleted rows are bumped too so no row anywhere keeps a sub-floor interval, but
        # their schedules are already gone and must not be re-issued.
        schemas = list(
            ExternalDataSchema.objects.filter(sync_frequency_interval__lt=SYNC_FREQUENCY_FLOOR).select_related("source")
        )

        if not schemas:
            logger.info("No schemas below the 5-minute floor — nothing to do")
            return

        live_schemas = [schema for schema in schemas if not schema.deleted]
        cdc_sources = {
            schema.source.id: schema.source
            for schema in live_schemas
            if schema.sync_type == ExternalDataSchema.SyncType.CDC
        }

        for schema in schemas:
            logger.info(
                "Schema below the 5-minute floor",
                schema_id=str(schema.id),
                team_id=schema.team_id,
                name=schema.name,
                source_id=str(schema.source_id),
                sync_type=schema.sync_type,
                sync_frequency_interval=str(schema.sync_frequency_interval),
                deleted=schema.deleted,
            )

        if dry_run:
            logger.info(
                "Dry run — no changes made",
                total=len(schemas),
                schedules_to_update=len(live_schemas),
                cdc_extraction_schedules_to_update=len(cdc_sources),
            )
            return

        if not settings.TEST:
            confirm = input(
                f"\n\tWill set {len(schemas)} schemas to a 5-minute interval and re-issue "
                f"{len(live_schemas)} sync schedules. Proceed? (y/n) "
            )
            if confirm.strip().lower() != "y":
                logger.info("Aborting")
                return

        # Set the floor in memory first so the re-issued schedules pick it up, but persist the
        # database interval only after the schedule update succeeds. Persisting first would make a
        # failed schedule update non-retryable: the row would report 5 minutes (no longer matching
        # the sub-floor query) while Temporal kept running at the old cadence, and a rerun would
        # skip it. Skipped schemas (never activated, no schedule) and soft-deleted schemas (schedule
        # already gone) have nothing to drift, so they are persisted regardless.
        for schema in schemas:
            schema.sync_frequency_interval = SYNC_FREQUENCY_FLOOR

        skipped, failures = bulk_update_external_data_job_schedules(live_schemas)
        failed_ids = {schema_id for schema_id, _ in failures}

        persisted = 0
        for schema in schemas:
            if str(schema.id) in failed_ids:
                continue
            # An ops-driven migration, not a user edit — keep it out of the activity feed.
            schema.save(update_fields=["sync_frequency_interval", "updated_at"], skip_activity_log=True)
            persisted += 1

        for schema_id, exc in failures:
            logger.exception(
                "Error updating external data schema schedule", external_data_schema_id=schema_id, exc_info=exc
            )

        # The CDC extraction schedule's interval is derived (from the database) from the source's
        # fastest CDC schema, so it must be re-derived now that the persisted schemas were slowed
        # down. A schema whose schedule update failed keeps its sub-floor interval, so the derived
        # extraction interval stays consistent with what Temporal is actually running.
        extraction_failures = 0
        for source in cdc_sources.values():
            try:
                sync_cdc_extraction_schedule(source)
            except Exception as exc:
                extraction_failures += 1
                logger.exception(
                    "Error updating CDC extraction schedule", external_data_source_id=str(source.id), exc_info=exc
                )

        logger.info(
            "Done!",
            updated=persisted,
            not_persisted_after_schedule_failure=len(failures),
            schedules_updated=len(live_schemas) - len(skipped) - len(failures),
            schedules_skipped=len(skipped),
            schedules_failed=len(failures),
            cdc_extraction_schedules_updated=len(cdc_sources) - extraction_failures,
            cdc_extraction_schedules_failed=extraction_failures,
        )
