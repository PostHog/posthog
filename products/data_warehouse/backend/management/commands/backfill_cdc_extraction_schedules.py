"""Backfill / re-issue per-source CDC extraction Temporal schedules.

Re-creates each source's ``cdc-extraction-{source_id}`` schedule from the Postgres source
of truth, which re-encrypts its workflow input under the current key. Idempotent: the
update path re-issues existing schedules; a missing schedule is created.

Only sources that currently have at least one active CDC schema (``sync_type=CDC``,
``should_sync=True``, not deleted) are processed — the per-source interval is the minimum
sync frequency across those schemas, matching ``sync_cdc_extraction_schedule``. Sources
that have lost all active CDC schemas are left untouched (the live deletion path handles
those at write time).

Usage:
    # Dry-run (default) — counts sources, upserts nothing
    python manage.py backfill_cdc_extraction_schedules

    # Live run
    python manage.py backfill_cdc_extraction_schedules --live-run

    # Restrict to a specific source type
    python manage.py backfill_cdc_extraction_schedules --live-run --source-type Postgres

    # Restrict to a specific team
    python manage.py backfill_cdc_extraction_schedules --live-run --team-id 2
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand

import structlog

from products.data_warehouse.backend.logic.data_load.service import bulk_sync_cdc_extraction_schedules, cdc_min_interval
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Backfill / re-issue per-source CDC extraction Temporal schedules."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--live-run",
            action="store_true",
            help="Actually upsert schedules (default is dry-run).",
        )
        parser.add_argument(
            "--source-type",
            type=str,
            default=None,
            help="Restrict to a specific source type (e.g. Postgres, MySQL).",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            default=None,
            help="Restrict to sources belonging to this team.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        live_run: bool = options["live_run"]
        source_type_filter: str | None = options["source_type"]
        team_id_filter: int | None = options["team_id"]

        # Excluding `source__deleted=True` guards against deleted sources whose schemas were
        # left non-deleted: `ExternalDataSource.soft_delete()` tears down the CDC schedule but
        # does not cascade to schemas, so a fleet-wide sweep keyed only on schema state could
        # otherwise resurrect the schedule for a deleted source. Mirrors `sync_cdc_extraction_schedule`.
        schema_qs = (
            ExternalDataSchema.objects.filter(
                sync_type=ExternalDataSchema.SyncType.CDC,
                should_sync=True,
            )
            .exclude(deleted=True)
            .exclude(source__deleted=True)
            .exclude(source__access_method=ExternalDataSource.AccessMethod.DIRECT)
            .select_related("source")
        )
        if source_type_filter is not None:
            schema_qs = schema_qs.filter(source__source_type=source_type_filter)
        if team_id_filter is not None:
            schema_qs = schema_qs.filter(team_id=team_id_filter)

        # One schedule per source; `cdc_min_interval` collapses each source's schema
        # intervals to the value `sync_cdc_extraction_schedule` would compute per source.
        sources: dict[Any, ExternalDataSource] = {}
        intervals: dict[Any, list[timedelta | None]] = defaultdict(list)
        for schema in schema_qs.iterator(chunk_size=500):
            sources[schema.source_id] = schema.source
            intervals[schema.source_id].append(schema.sync_frequency_interval)

        source_intervals = [(source, cdc_min_interval(intervals[source_id])) for source_id, source in sources.items()]

        self.stdout.write(f"Found {len(source_intervals)} CDC sources to process (live_run={live_run}).")

        if not live_run:
            self.stdout.write(f"Done. processed={len(source_intervals)} failed=0")
            return

        failures = bulk_sync_cdc_extraction_schedules(source_intervals)
        for source_id, exc in failures:
            logger.exception("Failed to backfill CDC extraction schedule", source_id=source_id, exc_info=exc)

        processed = len(source_intervals) - len(failures)
        self.stdout.write(f"Done. processed={processed} failed={len(failures)}")
