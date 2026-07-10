"""Repair schemas mis-disabled (and duplicated) by the qualified/bare name mismatch.

Schema discovery once compared stored vs discovered names by raw equality, so a table named
under a different qualification than its stored row (`public.users` vs bare `users`) was read as
removed — disabling the live row and inserting an other-qualification duplicate. The discovery
fix stops this going forward; this command repairs rows already mangled.

Only acts on the unambiguous fingerprint: a source with two same-table rows (one qualified, one
bare) where exactly one carries the live table (``table_id``) and the other is a clean phantom
(no ``table_id``, never synced, disabled). It re-enables the live row via ``update_should_sync``
(reconciling the Temporal schedule) and soft-deletes the phantom. Anything ambiguous (two live
rows, a synced twin, a lone disabled row) is reported and left untouched. Idempotent.

Usage:
    # Dry-run (default) — reports what it would do, changes nothing
    python manage.py repair_qualified_schema_duplicates

    # Live run
    python manage.py repair_qualified_schema_duplicates --live-run

    # Restrict to one source / team (defaults to source-type Postgres)
    python manage.py repair_qualified_schema_duplicates --live-run --source-id <uuid>
    python manage.py repair_qualified_schema_duplicates --live-run --team-id 2
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from django.core.management.base import BaseCommand

import structlog

from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource, update_should_sync
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)


def _is_qualified(name: str) -> bool:
    return "." in name


def _unqualified(name: str) -> str:
    return name.rpartition(".")[2]


class Command(BaseCommand):
    help = "Re-enable live schemas wrongly disabled by the qualified/bare name mismatch and soft-delete phantom duplicates."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--live-run",
            action="store_true",
            help="Apply changes (default is dry-run).",
        )
        parser.add_argument(
            "--source-type",
            type=str,
            default=ExternalDataSourceType.POSTGRES,
            help="Source type to repair (default: Postgres — the only type affected by this bug).",
        )
        parser.add_argument(
            "--source-id",
            type=str,
            default=None,
            help="Restrict to a single ExternalDataSource id.",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            default=None,
            help="Restrict to sources belonging to this team.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        live_run: bool = options["live_run"]
        source_type_filter: str = options["source_type"]
        source_id_filter: str | None = options["source_id"]
        team_id_filter: int | None = options["team_id"]

        sources = ExternalDataSource.objects.exclude(deleted=True).filter(source_type=source_type_filter)
        if source_id_filter is not None:
            sources = sources.filter(id=source_id_filter)
        if team_id_filter is not None:
            sources = sources.filter(team_id=team_id_filter)

        reenabled = 0
        soft_deleted = 0
        skipped_ambiguous = 0

        for source in sources.iterator(chunk_size=200):
            schemas = list(ExternalDataSchema.objects.filter(source_id=source.id).exclude(deleted=True))

            by_table: dict[str, list[ExternalDataSchema]] = defaultdict(list)
            for schema in schemas:
                by_table[_unqualified(schema.name)].append(schema)

            for unqualified, group in by_table.items():
                if len(group) < 2:
                    continue

                live = [s for s in group if s.table_id is not None]
                phantoms = [s for s in group if s.table_id is None and s.last_synced_at is None and not s.should_sync]

                # One live row + a phantom of the other qualification is the bug fingerprint.
                # Two live rows = legit multi-schema; anything else is ambiguous — leave it.
                if len(live) != 1 or not phantoms:
                    if len(live) != 1:
                        skipped_ambiguous += 1
                        logger.info(
                            "Skipping ambiguous schema group",
                            source_id=str(source.id),
                            team_id=source.team_id,
                            table=unqualified,
                            names=[s.name for s in group],
                        )
                    continue

                live_schema = live[0]
                twins = [p for p in phantoms if _is_qualified(p.name) != _is_qualified(live_schema.name)]
                if not twins:
                    continue

                if not live_schema.should_sync:
                    self.stdout.write(
                        f"{'[live] ' if live_run else '[dry-run] '}re-enable {live_schema.name!r} "
                        f"(source={source.id}, team={source.team_id})"
                    )
                    if live_run:
                        update_should_sync(schema_id=str(live_schema.id), team_id=source.team_id, should_sync=True)
                    reenabled += 1

                for twin in twins:
                    self.stdout.write(
                        f"{'[live] ' if live_run else '[dry-run] '}soft-delete phantom {twin.name!r} "
                        f"(source={source.id}, team={source.team_id})"
                    )
                    if live_run:
                        twin.soft_delete()
                    soft_deleted += 1

        self.stdout.write(
            f"Done (live_run={live_run}). reenabled={reenabled} "
            f"soft_deleted={soft_deleted} skipped_ambiguous={skipped_ambiguous}"
        )
