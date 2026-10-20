from typing import Any

from django.core.management.base import BaseCommand

from products.alerts.backend.facade.contracts import INSIGHT_ALERT_EVENT_IDS
from products.alerts.backend.facade.destinations import bucket_report_lines
from products.alerts.backend.logic.destination_bucket_report import enabled_insight_alerts


class Command(BaseCommand):
    help = "List every destination of an enabled insight alert with the bucket it goes to at cutover."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Report one team only.")

    def handle(self, *args: Any, **options: Any) -> None:
        for line in bucket_report_lines(
            enabled_insight_alerts(team_id=options["team_id"]), allowed_event_ids=INSIGHT_ALERT_EVENT_IDS
        ):
            self.stdout.write(line)
