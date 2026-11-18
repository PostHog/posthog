from typing import cast

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.batch_exports.backend.logic.credentials_cleanup import (
    DESTINATION_TYPES,
    SKIPPED_NO_INTEGRATION,
    cleanup_batch_export_credentials,
    unresolved,
    verify_batch_export_credentials_cleanup,
)


class Command(BaseCommand):
    help = (
        "Remove inline credentials from batch export destination config when the destination uses an "
        "Integration of its team. Redshift COPY access keys move to AWS S3 Integrations. "
        "Destinations without an Integration are skipped unless --include-without-integration is set. "
        "Preview by default. After --execute, schedules are synced. Output contains counts only."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--execute", action="store_true", help="Write the planned changes.")
        parser.add_argument("--verify", action="store_true", help="Report remaining work without writes.")
        parser.add_argument(
            "--include-without-integration",
            action="store_true",
            help="Also clear inline credentials of destinations that have no Integration.",
        )
        parser.add_argument("--team-id", type=int, action="append", default=[], help="Select a team. Repeatable.")
        parser.add_argument(
            "--type", choices=DESTINATION_TYPES, action="append", default=[], help="Select a destination type."
        )
        parser.add_argument("--limit", type=int, default=None, help="Maximum destinations to process.")
        parser.add_argument("--batch-size", type=int, default=200, help="Destinations per batch.")

    def handle(self, *args: object, **options: object) -> None:
        execute = bool(options["execute"])
        verify = bool(options["verify"])
        include_without_integration = bool(options["include_without_integration"])
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

        if verify:
            self.stdout.write("Verification: nothing was written")
            counts = verify_batch_export_credentials_cleanup(
                include_without_integration=include_without_integration,
                team_ids=team_ids,
                destination_types=destination_types,
                batch_size=batch_size,
            )
        else:
            self.stdout.write("Execute" if execute else "Dry run: nothing was written")
            counts = cleanup_batch_export_credentials(
                execute=execute,
                include_without_integration=include_without_integration,
                team_ids=team_ids,
                destination_types=destination_types,
                limit=limit,
                batch_size=batch_size,
                on_batch=lambda size: self.stdout.write(f"Processed destinations: {size}"),
            )
        for key, count in sorted(counts.items(), key=lambda item: (item[0].destination_type, item[0].outcome)):
            self.stdout.write(f"{key.destination_type} {key.outcome}: {count}")
        self.stdout.write(f"Total outcomes: {sum(counts.values())}")
        without_integration = sum(count for key, count in counts.items() if key.outcome == SKIPPED_NO_INTEGRATION)
        self.stdout.write(
            f"Skipped without an integration: {without_integration} "
            "(set --include-without-integration to clear their inline credentials)"
        )
        if verify and unresolved(counts):
            raise CommandError("Batch export destinations still hold inline credentials.")
