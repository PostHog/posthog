"""Backfill per-source schema-discovery schedules for existing ExternalDataSource rows.

Schema discovery used to run inline on every per-schema sync workflow, which scaled
disastrously for sources with thousands of schemas. It now runs on its own per-source
Temporal schedule (``discover-schemas-{source_id}``) created at source-creation time —
this command ensures the schedule exists for sources that were created before that
wiring landed.

Idempotent: safe to re-run. ``bulk_sync_discover_schemas_schedules`` upserts each
schedule (creates if missing, updates otherwise) over a single shared Temporal
connection, running the per-source upserts concurrently.

Usage:
    # Dry-run (default) — counts sources, creates nothing
    python manage.py backfill_discovery_schedules

    # Live run
    python manage.py backfill_discovery_schedules --live-run

    # Restrict to a specific source type
    python manage.py backfill_discovery_schedules --live-run --source-type Slack

    # Restrict to a specific team
    python manage.py backfill_discovery_schedules --live-run --team-id 2
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

import structlog

from products.data_warehouse.backend.logic.data_load.service import bulk_sync_discover_schemas_schedules
from products.warehouse_sources.backend.facade.models import ExternalDataSource
from products.warehouse_sources.backend.facade.source_management import SourceRegistry
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Backfill per-source schema-discovery Temporal schedules for existing ExternalDataSource rows."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--live-run",
            action="store_true",
            help="Actually create schedules (default is dry-run).",
        )
        parser.add_argument(
            "--source-type",
            type=str,
            default=None,
            help="Restrict to a specific source type (e.g. Slack, Stripe).",
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

        # Direct-query sources resolve schemas at query time and opt out of all
        # background sync — they should not get a discovery schedule.
        queryset = ExternalDataSource.objects.exclude(deleted=True).exclude(
            access_method=ExternalDataSource.AccessMethod.DIRECT
        )
        if source_type_filter is not None:
            queryset = queryset.filter(source_type=source_type_filter)
        if team_id_filter is not None:
            queryset = queryset.filter(team_id=team_id_filter)

        eligible: list[ExternalDataSource] = []
        skipped_unregistered = 0

        for source in queryset.iterator(chunk_size=200):
            try:
                source_type_enum = ExternalDataSourceType(source.source_type)
            except ValueError:
                skipped_unregistered += 1
                continue

            if not SourceRegistry.is_registered(source_type_enum):
                skipped_unregistered += 1
                continue

            eligible.append(source)

        self.stdout.write(f"Found {len(eligible)} sources to process (live_run={live_run}).")

        if not live_run:
            self.stdout.write(f"Done. processed={len(eligible)} skipped_unregistered={skipped_unregistered} failed=0")
            return

        # `bulk_sync_discover_schemas_schedules` upserts over a single shared Temporal
        # connection and runs the per-source upserts concurrently — far faster than
        # reconnecting per source. It returns failures instead of raising, so a single bad
        # source doesn't abort the backfill.
        failures = bulk_sync_discover_schemas_schedules(eligible)
        for source_id, exc in failures:
            logger.exception("Failed to backfill discovery schedule", source_id=source_id, exc_info=exc)

        processed = len(eligible) - len(failures)
        self.stdout.write(
            f"Done. processed={processed} skipped_unregistered={skipped_unregistered} failed={len(failures)}"
        )
