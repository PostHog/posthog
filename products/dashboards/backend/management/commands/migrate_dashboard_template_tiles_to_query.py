from typing import Any

from django.core.management.base import BaseCommand, CommandParser

import structlog

from posthog.schema import InsightVizNode

from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query

from products.dashboards.backend.models.dashboard_templates import DashboardTemplate

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = (
        "Convert legacy `filters` tiles on dashboard templates to `query` — the same conversion as "
        "migration 0530, for templates created since it ran. Dry-run by default; pass --live to write."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--live", action="store_true", help="Write changes (default is a read-only report)")

    def handle(self, *args: Any, **options: Any) -> None:
        live: bool = options["live"]
        if not live:
            self.stdout.write(self.style.WARNING("Dry run — pass --live to write"))

        updated_templates = 0
        converted_tiles = 0
        errors: dict[str, list[str]] = {}

        for template in DashboardTemplate.objects.exclude(tiles__isnull=True).iterator(chunk_size=100):
            changed = False
            for tile in template.tiles or []:
                if not isinstance(tile, dict) or "filters" not in tile:
                    continue
                if not tile.get("query"):
                    try:
                        # allow_variables matches migration 0530 — template tiles may carry template variables
                        source = filter_to_query(tile["filters"], allow_variables=True)
                        tile["query"] = InsightVizNode(source=source).model_dump(exclude_none=True)
                    except Exception as e:
                        errors.setdefault(type(e).__name__, []).append(str(template.id))
                        continue
                    converted_tiles += 1
                # A tile with both keys keeps its query — runtime reads query first, so filters is dead weight.
                del tile["filters"]
                changed = True
            if changed:
                updated_templates += 1
                if live:
                    template.save(update_fields=["tiles"])

        failed = sum(len(ids) for ids in errors.values())
        verb = "Updated" if live else "Would update"
        style = self.style.SUCCESS if failed == 0 else self.style.WARNING
        self.stdout.write(
            style(f"{verb} {updated_templates} templates ({converted_tiles} tiles converted, {failed} tiles failed)")
        )
        for error_type, ids in sorted(errors.items(), key=lambda kv: -len(kv[1])):
            self.stdout.write(f"  {error_type}: {len(ids)} tiles, template ids e.g. {ids[:5]}")
