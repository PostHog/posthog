"""Remove destination credentials and input values that older code stored in plain text.

Three stores hold them, and each step cleans one:

- `debug-logs`: debug lines in `log_entries` where native and Segment destinations dumped
  their resolved config. Needs `--debug-logs-before`, the deploy time of the redaction fix.
- `activity-logs`: activity log rows that recorded destination input values before the log masked them.
- `mapping-secrets`: secret mapping inputs, moved into the destination's encrypted inputs.

Dry run by default. Every step skips what is already clean, so a rerun is safe.
"""

from datetime import datetime
from typing import Any, Optional

from django.core.management.base import BaseCommand, CommandError

from posthog.clickhouse.log_entries import LOG_ENTRIES_SHARDED_TABLE

from products.cdp.backend.services.destination_activity_logs import (
    ActivityLogScope,
    count_unmasked_activity_logs,
    mask_activity_logs,
)
from products.cdp.backend.services.destination_debug_logs import (
    DebugLogScope,
    count_debug_logs,
    delete_debug_logs,
    find_destination_functions,
)
from products.cdp.backend.services.destination_mapping_secrets import find_mapping_secret_keys, move_mapping_secrets

STEPS = ["debug-logs", "activity-logs", "mapping-secrets"]


class Command(BaseCommand):
    help = "Remove destination credentials and input values stored in plain text. Dry run by default."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--step", choices=STEPS, action="append", help="Run only this step. Repeat to run several. Default: all."
        )
        parser.add_argument(
            "--debug-logs-before",
            help="ISO 8601 cutoff for the debug-logs step. Use the deploy time of the log redaction fix.",
        )
        parser.add_argument("--team-id", type=int, default=None, help="Restrict to one team.")
        parser.add_argument("--commit", action="store_true", help="Write the changes. Omit for a dry run.")

    def handle(self, *args: Any, **options: Any) -> None:
        steps = options["step"] or STEPS
        debug_logs_before = self._parse_cutoff(options["debug_logs_before"]) if "debug-logs" in steps else None
        if "debug-logs" in steps and debug_logs_before is None:
            raise CommandError("The debug-logs step needs --debug-logs-before, or leave it out with --step.")

        team_id: Optional[int] = options["team_id"]
        commit: bool = options["commit"]
        if debug_logs_before is not None:
            self._debug_logs(DebugLogScope(before=debug_logs_before, team_id=team_id), commit)
        if "activity-logs" in steps:
            self._activity_logs(ActivityLogScope(team_id=team_id), commit)
        if "mapping-secrets" in steps:
            self._mapping_secrets(team_id, commit)
        if not commit:
            self.stdout.write("Dry run. Re-run with --commit to write the changes.")

    def _parse_cutoff(self, value: Optional[str]) -> Optional[datetime]:
        if value is None:
            return None
        try:
            cutoff = datetime.fromisoformat(value)
        except ValueError:
            raise CommandError(
                "--debug-logs-before must be an ISO 8601 datetime, for example 2026-09-18T10:00:00+00:00"
            )
        if cutoff.tzinfo is None:
            raise CommandError("--debug-logs-before must carry a timezone offset")
        return cutoff

    def _debug_logs(self, scope: DebugLogScope, commit: bool) -> None:
        functions = find_destination_functions(scope)
        count = count_debug_logs(scope, functions)
        self.stdout.write(
            f"debug-logs: {count.lines} lines across {count.functions} functions in {count.teams} teams "
            f"(first {count.first_seen}, last {count.last_seen})"
        )
        if commit and count.lines:
            delete_debug_logs(scope, functions)
            self.stdout.write(
                "debug-logs: delete submitted. Watch progress with: "
                f"SELECT is_done, parts_to_do, latest_fail_reason FROM system.mutations "
                f"WHERE table = '{LOG_ENTRIES_SHARDED_TABLE}' ORDER BY create_time DESC LIMIT 5"
            )

    def _activity_logs(self, scope: ActivityLogScope, commit: bool) -> None:
        if commit:
            self.stdout.write(f"activity-logs: masked {mask_activity_logs(scope)} rows")
            return
        count = count_unmasked_activity_logs(scope)
        self.stdout.write(f"activity-logs: {count.rows} rows in {count.teams} teams to mask")

    def _mapping_secrets(self, team_id: Optional[int], commit: bool) -> None:
        keys = find_mapping_secret_keys(team_id)
        movable = [key for key in keys if key.movable]
        self.stdout.write(f"mapping-secrets: {len(movable)} of {len(keys)} secret mapping keys can move")
        for key in keys:
            if not key.movable:
                self.stdout.write(
                    f"mapping-secrets: skipped team {key.team_id} function {key.function_id} "
                    f"key {key.key}: {key.skip_reason}"
                )
        if commit and movable:
            self.stdout.write(f"mapping-secrets: moved keys on {move_mapping_secrets(movable)} functions")
