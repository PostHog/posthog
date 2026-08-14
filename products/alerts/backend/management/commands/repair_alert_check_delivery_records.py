from datetime import datetime
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from posthog.schema import AlertState

from products.alerts.backend.models.alert import AlertCheck


class Command(BaseCommand):
    help = (
        "Clear delivery records on ERRORED alert checks stamped while the error-email path was "
        "disabled. Only notify_alert stamps notification_sent_at, and its ERRORED branch sent "
        "nothing before the error email was restored — so ERRORED + stamped + pre-cutoff rows "
        "are exactly the false 'targets notified' population, excluding rows with delivery receipts. "
        "Dry-run by default."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--before",
            required=True,
            help="ISO-8601 cutoff (tz-aware): the deploy time of the error-email restore (PR #79150)",
        )
        parser.add_argument("--execute", action="store_true", help="Apply the repair (default: dry-run)")

    def handle(self, *args: Any, **options: Any) -> None:
        cutoff = datetime.fromisoformat(options["before"])
        if cutoff.tzinfo is None:
            raise CommandError("--before must be timezone-aware, e.g. 2026-08-12T00:00:00+00:00")

        matches = AlertCheck.objects.filter(
            state=AlertState.ERRORED,
            notification_sent_at__isnull=False,
            created_at__lt=cutoff,
            deliveries__isnull=True,
        )
        per_team = matches.values("alert_configuration__team_id").annotate(rows=Count("id")).order_by("-rows")
        total = matches.count()
        for row in per_team:
            self.stdout.write(f"team {row['alert_configuration__team_id']}: {row['rows']} rows")
        self.stdout.write(f"total: {total} rows")

        if not options["execute"]:
            self.stdout.write(self.style.WARNING("Dry-run only. Re-run with --execute to repair."))
            return

        updated = matches.update(targets_notified={}, notification_sent_at=None)
        self.stdout.write(self.style.SUCCESS(f"Cleared delivery records on {updated} rows"))
