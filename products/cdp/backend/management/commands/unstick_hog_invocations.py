"""Mark CDP runs that are stuck on `running` as failed so they can be re-run.

A run gets stuck when its invocation was dropped without a terminal lifecycle
row ever being produced. The known cause was re-running an invocation of a
disabled destination, fixed at the source, but the rows written before that fix
stay stuck for the 30 days the ClickHouse table retains them, and any future
drop path with the same gap would land here too.

Runs against one team at a time. Start with a dry run, which prints what it
would touch and writes nothing.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from products.cdp.backend.services.stuck_invocations import MAX_WINDOW_DAYS, StuckInvocationScope, unstick_invocations

FUNCTION_KINDS = ["hog_function", "hog_flow"]

# A hog flow legitimately sits on `running` for as long as its longest delay
# step, and nothing in the stored row says how long that is. An operator has to
# pick an age past it, so flows are opt-in rather than reachable by default.
DEFAULT_MIN_AGE_HOURS = 24
MIN_AGE_FLOOR_HOURS = 1


class Command(BaseCommand):
    help = (
        "Mark hog invocations stuck on 'running' as failed so the Runs tab stops "
        "showing them in flight and they become re-runnable. Dry run by default."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="Team to scan.")
        parser.add_argument(
            "--function-kind",
            choices=FUNCTION_KINDS,
            default="hog_function",
            help="Default: hog_function. Read the --min-age-hours help before using hog_flow.",
        )
        parser.add_argument("--function-id", default=None, help="Restrict to one destination or workflow.")
        parser.add_argument(
            "--invocation-id",
            action="append",
            default=None,
            dest="invocation_ids",
            help="Repeatable. Restrict to specific invocations.",
        )
        parser.add_argument(
            "--min-age-hours",
            type=int,
            default=DEFAULT_MIN_AGE_HOURS,
            help=(
                f"Only touch runs last scheduled at least this long ago (default {DEFAULT_MIN_AGE_HOURS}, "
                f"minimum {MIN_AGE_FLOOR_HOURS}). A hog flow waiting on a delay step is genuinely running, "
                "so set this past the longest delay in the flow."
            ),
        )
        parser.add_argument("--limit", type=int, default=1000, help="Cap on invocations touched per run.")
        parser.add_argument("--commit", action="store_true", help="Write the terminal rows. Omit for a dry run.")

    def handle(self, *args: Any, **options: Any) -> None:
        min_age_hours = options["min_age_hours"]
        if min_age_hours < MIN_AGE_FLOOR_HOURS:
            raise CommandError(f"--min-age-hours must be at least {MIN_AGE_FLOOR_HOURS}")
        if min_age_hours >= MAX_WINDOW_DAYS * 24:
            raise CommandError(
                f"--min-age-hours must be under {MAX_WINDOW_DAYS * 24}, the ClickHouse retention on these rows"
            )

        scope = StuckInvocationScope(
            team_id=options["team_id"],
            function_kind=options["function_kind"],
            function_id=options["function_id"],
            invocation_ids=tuple(options["invocation_ids"] or ()),
            min_age=timedelta(hours=min_age_hours),
            limit=options["limit"],
        )
        dry_run = not options["commit"]

        stuck = unstick_invocations(scope, now=datetime.now(tz=UTC), dry_run=dry_run)

        for invocation in stuck:
            self.stdout.write(
                f"{invocation.invocation_id} function={invocation.function_id} "
                f"scheduled_at={invocation.scheduled_at.isoformat()}"
            )

        verb = "would mark" if dry_run else "marked"
        self.stdout.write(f"{verb} {len(stuck)} invocation(s) failed for team {scope.team_id}")
        if dry_run and stuck:
            self.stdout.write("Re-run with --commit to write the terminal rows.")
