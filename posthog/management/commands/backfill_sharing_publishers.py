from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from posthog.sharing_attribution import SharingAttributionBackfill


class Command(BaseCommand):
    help = "Fill missing sharing publishers from the latest available sharing-enabled activity logs."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--batch-size", type=int, default=1000)
        parser.add_argument("--team-id", type=int, help="Limit the backfill to one project.")
        parser.add_argument("--dry-run", action="store_true", help="Report matches without changing any rows.")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be positive")
        scanned = matched = 0
        for batch in SharingAttributionBackfill().run(
            batch_size=options["batch_size"], team_id=options["team_id"], dry_run=options["dry_run"]
        ):
            scanned += batch.scanned
            matched += batch.updated
            self.stdout.write(f"{batch.kind}: scanned {batch.scanned}, matched {batch.updated}")
        action = "Would update" if options["dry_run"] else "Updated"
        self.stdout.write(f"{action} {matched} of {scanned} configurations. Missing history remains unattributed.")
