from collections import Counter
from typing import Any

from django.core.management.base import BaseCommand

from products.alerts.backend.facade.destinations import team_delivery_paths
from products.alerts.backend.logic.alert_email import INSIGHT_ALERT_ERRORED_EVENT_ID
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.platform_cutover import cut_over_team
from products.alerts_platform.backend.facade.contracts import SourceKind
from products.cdp.backend.internal_events import LEGACY_INSIGHT_ALERT_EVENT


class Command(BaseCommand):
    help = "Hand one team's insight alerts to the alerts platform. Safe to run again."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="The team to move.")

    def handle(self, *args: Any, **options: Any) -> None:
        team_id = options["team_id"]
        alert_ids = [
            str(alert_id)
            for alert_id in AlertConfiguration.objects.filter(team_id=team_id).values_list("id", flat=True)
        ]
        paths = team_delivery_paths(
            source=SourceKind.INSIGHT,
            team_id=team_id,
            alert_ids=alert_ids,
            allowed_event_ids=[LEGACY_INSIGHT_ALERT_EVENT, INSIGHT_ALERT_ERRORED_EVENT_ID],
        )
        for alert_id, choice in paths.items():
            if choice.reason is not None:
                self.stdout.write(f"alert={alert_id} path={choice.path} reason={choice.reason}")
        results = cut_over_team(team_id)
        for result in results:
            if result.skipped is not None:
                self.stdout.write(f"alert={result.alert_id} skipped={result.skipped}")
        delivery = Counter(str(choice.path) for choice in paths.values())
        outcomes = Counter(str(result.skipped or "moved") for result in results)
        self.stdout.write(f"team={team_id} {dict(outcomes) or 'no alerts'} paths={dict(delivery)}")
