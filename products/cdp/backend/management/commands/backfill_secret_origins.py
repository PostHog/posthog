from typing import Any

from django.core.management.base import BaseCommand, CommandError

from products.cdp.backend.services.secret_origins_backfill import backfill_secret_origins


class Command(BaseCommand):
    help = (
        "Store the origins each legacy secret input of a hog function may be sent to, from its template's auth "
        "declaration. Dry run by default."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--commit", action="store_true", help="Write the changes. Omit for a dry run.")
        parser.add_argument("--team-id", type=int, default=None, help="Restrict to one team.")
        parser.add_argument(
            "--batch-size", type=int, default=500, help="Rows per page. The command logs its progress after each page."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        commit: bool = options["commit"]
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be at least 1.")
        report = backfill_secret_origins(commit=commit, team_id=options["team_id"], batch_size=options["batch_size"])
        for outcome, count in sorted(report.outcomes.items()):
            self.stdout.write(f"secrets {outcome}: {count}")
        # A template that declares no auth leaves its secrets open to any origin, so it is a candidate to migrate.
        for template_id, count in report.any_origin_templates.most_common():
            self.stdout.write(f"functions with a secret open to any origin, by template: {template_id}={count}")
        if commit:
            self.stdout.write(f"rows written: {report.rows_written}")
        else:
            self.stdout.write(f"rows to write: {report.rows_to_write}")
            self.stdout.write("Dry run. Re-run with --commit to write the changes.")
        self.stdout.write(f"rows that failed: {report.rows_failed}")
        if report.rows_failed:
            raise CommandError(f"{report.rows_failed} rows failed. See the secret_origins_backfill_row_failed logs.")
