from typing import Any

from django.core.management.base import BaseCommand

from products.cdp.backend.services.secret_origins_backfill import backfill_secret_origins


class Command(BaseCommand):
    help = "Bind stored secret inputs of hog functions to the origins they may be sent to. Dry run by default."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--apply", action="store_true", help="Write the changes. Omit for a dry run.")
        parser.add_argument("--team-id", type=int, default=None, help="Restrict to one team.")
        parser.add_argument("--batch-size", type=int, default=500, help="Rows to load per query.")

    def handle(self, *args: Any, **options: Any) -> None:
        apply: bool = options["apply"]
        report = backfill_secret_origins(apply=apply, team_id=options["team_id"], batch_size=options["batch_size"])
        for (store, outcome), count in sorted(report.outcomes.items()):
            self.stdout.write(f"{store} secrets {outcome}: {count}")
        # An unbound secret can go to any origin, so a person decides whether its function needs a change.
        for template_id, count in report.unbound_templates.most_common():
            self.stdout.write(f"unbound by template: {template_id}={count}")
        self.stdout.write(f"rows to write: {report.rows_to_write}")
        if apply:
            self.stdout.write(
                f"rows written: {report.rows_written}, skipped as changed since the scan: {report.rows_changed}"
            )
        else:
            self.stdout.write("Dry run. Re-run with --apply to write the changes.")
