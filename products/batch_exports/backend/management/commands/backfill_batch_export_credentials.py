from typing import cast

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.batch_exports.backend.logic.credentials_backfill import (
    DESTINATION_TYPES,
    NEEDS_WORK,
    backfill_batch_export_credentials,
    verify_batch_export_credentials,
)


class Command(BaseCommand):
    help = (
        "Move inline batch export credentials into Integrations. Preview by default. "
        "After --execute, schedules are synced unless --no-sync-schedules is set. "
        "Use update_batch_export_schedules to sync schedules later. Output contains counts only."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--execute", action="store_true", help="Write the planned changes.")
        parser.add_argument("--verify", action="store_true", help="Report remaining work without writes.")
        parser.add_argument("--team-id", type=int, action="append", default=[], help="Select a team. Repeatable.")
        parser.add_argument(
            "--type",
            choices=DESTINATION_TYPES,
            action="append",
            default=[],
            help="Select a destination type. Repeatable.",
        )
        parser.add_argument("--limit", type=int, default=None, help="Maximum destinations to process during backfill.")
        parser.add_argument("--batch-size", type=int, default=200, help="Destinations per batch.")
        parser.add_argument("--no-sync-schedules", action="store_true", help="Do not sync schedules after writes.")

    def handle(self, *args: object, **options: object) -> None:
        execute = bool(options["execute"])
        verify = bool(options["verify"])
        batch_size = cast(int, options["batch_size"])
        limit = cast(int | None, options["limit"])
        team_ids = cast(list[int], options["team_id"])
        destination_types = cast(list[str], options["type"])
        if execute and verify:
            raise CommandError("Use --verify without --execute.")
        if batch_size < 1:
            raise CommandError("--batch-size must be at least 1.")
        if limit is not None and limit < 0:
            raise CommandError("--limit must be zero or greater.")
        if any(kind not in DESTINATION_TYPES for kind in destination_types):
            raise CommandError("Select a supported destination type.")

        if verify:
            self.stdout.write("Verification: nothing was written")
            counts = verify_batch_export_credentials(
                team_ids=team_ids, destination_types=destination_types, batch_size=batch_size
            )
        else:
            self.stdout.write("Execute" if execute else "Dry run: nothing was written")
            counts = backfill_batch_export_credentials(
                execute=execute,
                team_ids=team_ids,
                destination_types=destination_types,
                limit=limit,
                batch_size=batch_size,
                sync_schedules=not options["no_sync_schedules"],
                on_batch=lambda size: self.stdout.write(f"Processed destinations: {size}"),
            )
        for (destination_type, outcome), count in sorted(counts.items()):
            self.stdout.write(f"{destination_type} {outcome}: {count}")
        self.stdout.write(f"Total outcomes: {sum(counts.values())}")
        if verify and any(count for (_, outcome), count in counts.items() if outcome in NEEDS_WORK):
            raise CommandError("Batch export credentials still need work.")
