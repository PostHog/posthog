"""Queue a shadow abuse score for every existing enabled destination and transformation.

Each function gets one task on the queue the save-time task uses. The tasks score regardless of the team flag,
record the content hash, and tag their events with this run's ID. Turning off the `cdp-abuse-classifier-backfill`
flag stops the run before its next function, both here and in tasks already queued. Passing an earlier run's
`--run-id` resumes it: functions that run already scored are skipped, and failed or dropped ones are queued again.
"""

import time
import uuid
from typing import Any

from django.core.management.base import BaseCommand

from products.cdp.backend.abuse import shadow
from products.cdp.backend.tasks.abuse_classification import backfill_hog_function_abuse_score


class Command(BaseCommand):
    help = "Queue a shadow abuse score for each enabled destination and transformation."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--exclude-team", type=int, action="append", default=[], help="Skip a team. Repeatable.")
        parser.add_argument(
            "--exclude-organization", action="append", default=[], help="Skip an organization by ID. Repeatable."
        )
        parser.add_argument("--limit", type=int, help="Queue at most this many functions.")
        parser.add_argument("--after-id", help="Resume after this hog function ID, as printed by an earlier run.")
        parser.add_argument("--rate", type=float, default=5.0, help="Tasks queued per second. 0 means no limit.")
        parser.add_argument("--dry-run", action="store_true", help="Print the count and queue nothing.")
        parser.add_argument("--run-id", help="Resume an earlier run, skipping the functions it already scored.")

    def handle(self, *args: Any, **options: Any) -> None:
        hog_functions = (
            shadow.scorable_hog_functions()
            .exclude(team_id__in=options["exclude_team"])
            .exclude(team__organization_id__in=options["exclude_organization"])
            .order_by("id")
        )
        if options["after_id"]:
            hog_functions = hog_functions.filter(id__gt=options["after_id"])
        if options["limit"] is not None:
            hog_functions = hog_functions[: options["limit"]]
        targets = list(hog_functions.values_list("id", "team_id"))

        if options["dry_run"]:
            self.stdout.write(f"Dry run: {len(targets)} functions would be queued.")
            return

        run_id = options["run_id"] or uuid.uuid4().hex
        self.stdout.write(f"run_id {run_id}: considering {len(targets)} functions")
        queued = 0
        last_id = None
        for hog_function_id, team_id in targets:
            if not shadow.backfill_enabled():
                self.stdout.write(f"Kill switch {shadow.BACKFILL_FLAG} is off: stopped after {queued}.")
                break
            if options["run_id"] and shadow.scored_in_backfill(run_id, str(hog_function_id)):
                continue
            backfill_hog_function_abuse_score.delay(
                team_id=team_id, hog_function_id=str(hog_function_id), run_id=run_id
            )
            queued += 1
            last_id = hog_function_id
            if options["rate"] > 0:
                time.sleep(1 / options["rate"])
        self.stdout.write(
            f"run_id {run_id}: queued {queued}, last {last_id}. Resume with --run-id {run_id} to retry failures."
        )
