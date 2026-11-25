import argparse
from typing import Any

from django.core.management.base import BaseCommand, CommandError

import structlog

from products.alerts.backend.facade.api import detach_investigations_from_rows, teams_with_row_linked_investigations
from products.alerts_platform.backend.facade.created_at_backfill_command import add_copy_backfill_arguments

logger = structlog.get_logger(__name__)


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return number


class Command(BaseCommand):
    help = (
        "Clear the insight row on the investigations of insight alerts the alerts platform owns, per team, "
        "in batches. Every reader finds an investigation by its platform alert, so nothing reads the row link, "
        "and deleting a legacy row would otherwise delete its investigations. Writes nothing without --apply."
    )

    def add_arguments(self, parser: Any) -> None:
        add_copy_backfill_arguments(parser)
        parser.add_argument("--batch-size", type=_positive, default=500, help="Rows per update.")

    def handle(self, *args: Any, **options: Any) -> None:
        apply = options["apply"]
        team_ids = options["team_ids"] or teams_with_row_linked_investigations()
        verb = "detached" if apply else "to detach"
        total = 0
        failed: list[int] = []
        # One team at a time, so one team's failure leaves the rest done and a rerun finds only what is left.
        for team_id in team_ids:
            try:
                count = detach_investigations_from_rows(team_id, batch_size=options["batch_size"], apply=apply)
            except Exception:
                logger.exception("detach_insight_alert_investigations_failed", team_id=team_id)
                failed.append(team_id)
                continue
            total += count
            self.stdout.write(f"team {team_id}: {count} investigations {verb}")
        suffix = "" if apply else " (dry run)"
        self.stdout.write(f"{len(team_ids)} teams, {total} investigations {verb}{suffix}")
        if failed:
            raise CommandError(f"Failed for teams: {', '.join(map(str, failed))}")
