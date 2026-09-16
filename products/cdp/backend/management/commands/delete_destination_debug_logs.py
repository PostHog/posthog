"""Delete the plain-text debug log lines that native and segment destinations wrote
before their logs were redacted. Dry run by default; see the service module for what
is in scope.
"""

from datetime import datetime
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from posthog.clickhouse.log_entries import LOG_ENTRIES_SHARDED_TABLE

from products.cdp.backend.services.destination_debug_logs import (
    DebugLogScope,
    count_debug_logs,
    delete_debug_logs,
    find_destination_functions,
)


class Command(BaseCommand):
    help = (
        "Delete the debug log lines in which native and segment destinations logged their "
        "resolved inputs and request options in plain text. Dry run by default."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--before",
            required=True,
            help="ISO 8601 cutoff. Only lines older than this are touched. Use the deploy time of the redaction fix.",
        )
        parser.add_argument("--team-id", type=int, default=None, help="Restrict to one team.")
        parser.add_argument("--commit", action="store_true", help="Run the delete. Omit for a dry run.")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            before = datetime.fromisoformat(options["before"])
        except ValueError:
            raise CommandError("--before must be an ISO 8601 datetime, for example 2026-09-18T10:00:00+00:00")
        if before.tzinfo is None:
            raise CommandError("--before must carry a timezone offset")

        scope = DebugLogScope(before=before, team_id=options["team_id"])
        functions = find_destination_functions(scope)
        self.stdout.write(f"{len(functions)} native/segment functions in scope")

        count = count_debug_logs(scope, functions)
        self.stdout.write(
            f"{count.lines} debug lines across {count.functions} functions in {count.teams} teams "
            f"(first {count.first_seen}, last {count.last_seen})"
        )
        if not count.lines:
            return
        if not options["commit"]:
            self.stdout.write("Dry run. Re-run with --commit to delete them.")
            return

        delete_debug_logs(scope, functions)
        self.stdout.write(
            "Delete submitted. Watch progress with: "
            f"SELECT is_done, parts_to_do, latest_fail_reason FROM system.mutations "
            f"WHERE table = '{LOG_ENTRIES_SHARDED_TABLE}' ORDER BY create_time DESC LIMIT 5"
        )
