from typing import Any

from django.core.management.base import BaseCommand

from posthog.cdp.legacy_destination_migration import migrate_legacy_destinations


def _int_list(value: str | None) -> list[int] | None:
    return [int(part) for part in value.split(",")] if value else None


class Command(BaseCommand):
    help = "Migrate enabled onEvent plugin configs to legacy_destination hog functions"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Report what would be migrated, and change nothing")
        parser.add_argument("--team-ids", type=str, help="Comma separated team ids to limit the migration to")
        parser.add_argument("--plugin-config-ids", type=str, help="Comma separated plugin config ids to migrate")
        parser.add_argument(
            "--drop-unmapped-inputs",
            action="store_true",
            help="Migrate configs carrying inputs the template schema does not declare, dropping those inputs",
        )
        parser.add_argument("--batch-size", type=int, default=100, help="Plugin configs to load per batch")
        parser.add_argument("--limit", type=int, default=None, help="Stop after this many plugin configs")

    def handle(self, *args: Any, **options: Any) -> None:
        result = migrate_legacy_destinations(
            dry_run=options["dry_run"],
            team_ids=_int_list(options["team_ids"]),
            plugin_config_ids=_int_list(options["plugin_config_ids"]),
            drop_unmapped_inputs=options["drop_unmapped_inputs"],
            batch_size=options["batch_size"],
            limit=options["limit"],
        )

        prefix = "Would migrate" if options["dry_run"] else "Migrated"
        self.stdout.write(f"{prefix} {len(result.created)} plugin config(s), skipped {len(result.skipped)}")

        for plugin_config_id, reason in result.skipped.items():
            self.stdout.write(f"  skipped {plugin_config_id}: {reason}")

        for plugin_config_id, keys in result.dropped_inputs.items():
            self.stdout.write(f"  dropped inputs on {plugin_config_id}: {', '.join(keys)}")
