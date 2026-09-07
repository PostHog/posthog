import time
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.core.paginator import Paginator

import structlog

from posthog.models.entity_dependencies.registry import (
    EntityDependencyRegistryError,
    get_source,
    plan_instance_dependencies,
    registered_source_types,
    sync_instance_dependencies,
)

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = (
        "Rebuild entity dependency rows for every instance of a registered source type. Each instance is "
        "synced with the same idempotent diff that runs on save, so this is both the one-time backfill for "
        "a newly registered source and the repair tool for rows left stale by writes that skipped save(). "
        "Default dry-run; pass --live-run to write."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--source-type", required=True, help="Registered source entity type, e.g. hog_flow")
        parser.add_argument("--team-id", type=int, default=None, help="Limit to one team")
        parser.add_argument("--page-size", type=int, default=500, help="Instances per page (default: 500)")
        parser.add_argument("--live-run", action="store_true", help="Write changes; without it, only report")

    def handle(self, *args: Any, **options: Any) -> None:
        started = time.time()
        source_type: str = options["source_type"]
        live_run: bool = options["live_run"]

        try:
            source = get_source(source_type)
        except EntityDependencyRegistryError:
            raise CommandError(f"Unknown source type {source_type!r}. Registered: {registered_source_types()}")

        queryset = source.get_queryset().order_by("pk")
        if options["team_id"] is not None:
            queryset = queryset.filter(team_id=options["team_id"])

        mode = "LIVE" if live_run else "DRY RUN"
        self.stdout.write(f"Backfilling entity dependencies for {source_type} ({mode})")

        scanned = added = removed = errors = 0
        paginator = Paginator(queryset, options["page_size"])
        for page_number in paginator.page_range:
            for instance in paginator.page(page_number).object_list:
                scanned += 1
                try:
                    result = sync_instance_dependencies(instance) if live_run else plan_instance_dependencies(instance)
                except Exception as e:
                    errors += 1
                    logger.exception(
                        "entity_dependencies.backfill_instance_failed",
                        source_type=source_type,
                        source_id=str(instance.pk),
                    )
                    self.stderr.write(f"  failed {source_type} {instance.pk}: {e}")
                    continue
                added += result.added
                removed += result.removed
            if scanned % (options["page_size"] * 10) == 0:
                self.stdout.write(f"  {scanned}/{paginator.count} scanned")

        verb = "" if live_run else " (would be)"
        self.stdout.write(
            self.style.SUCCESS(
                f"Done in {time.time() - started:.1f}s: {scanned} {source_type} scanned, "
                f"{added} rows added{verb}, {removed} rows removed{verb}, {errors} errors"
            )
        )
        if not live_run and (added or removed):
            self.stdout.write(self.style.NOTICE("Run with --live-run to apply"))
        if errors:
            raise CommandError(f"{errors} instance(s) failed; see log")
