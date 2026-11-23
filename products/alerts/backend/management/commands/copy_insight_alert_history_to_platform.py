from typing import Any

from django.core.management.base import BaseCommand, CommandError

from products.alerts.backend.legacy_history_copy import check_history, team_alert_ids
from products.alerts_platform.backend.facade.api import copy_legacy_histories
from products.alerts_platform.backend.facade.contracts import SourceKind
from products.alerts_platform.backend.facade.created_at_backfill_command import add_copy_backfill_arguments

SOURCE = SourceKind.INSIGHT


class Command(BaseCommand):
    help = (
        "Copy each insight alert's AlertCheck rows from before the alerts platform's first check of it into "
        "the platform's history, skipping what the platform already holds. Investigations and delivery "
        "records are not copied. Writes nothing without --apply."
    )

    def add_arguments(self, parser: Any) -> None:
        add_copy_backfill_arguments(parser)
        parser.add_argument(
            "--check", action="store_true", help="Write nothing, list the alerts with rows left, fail if any."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        apply = options["apply"] and not options["check"]
        run = copy_legacy_histories(
            source_kind=SOURCE,
            team_ids=options["team_ids"],
            alert_ids=team_alert_ids,
            legacy_history=check_history,
            apply=apply,
        )
        for line in run.report(SOURCE, applied=apply, unfinished_only=options["check"]):
            self.stdout.write(line)
        if run.failed_team_ids:
            raise CommandError(f"Failed for teams: {', '.join(map(str, run.failed_team_ids))}")
        if options["check"] and run.unfinished:
            raise CommandError(f"{len(run.unfinished)} alerts have rows still to copy")
