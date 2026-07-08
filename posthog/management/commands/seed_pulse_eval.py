import uuid
import random
from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from posthog.models import Team
from posthog.models.event.util import create_event
from posthog.schema_enums import AlertState

from products.alerts.backend.models.alert import AlertConfiguration
from products.annotations.backend.models import Annotation
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.models.insight import Insight

# One deliberate story: steady volume for 4 weeks, then a delivery drop + pageview spike
# starting MOVEMENT_DAYS_AGO, with an annotation on the same day for the explain stage.
DAYS = 28
MOVEMENT_DAYS_AGO = 4
USERS = 40

# event name -> (daily base volume, movement multiplier applied from MOVEMENT_DAYS_AGO on)
EVENTS: dict[str, tuple[int, float]] = {
    "subscription_created": (25, 1.0),
    "subscription_delivered": (60, 0.45),  # the drop the movement detector should catch
    "subscription_delivery_failed": (3, 3.0),  # failure spike, same story
    "$pageview": (90, 1.8),  # the spike
    "$feature_flag_called": (70, 1.0),
    "recording_watched": (30, 1.0),
}
SPARSE_EVENT = "pulse_eval_rare_event"  # 2 events total -> the honesty probe stays quiet


def _trends_query(event: str) -> dict[str, Any]:
    return {
        "kind": "InsightVizNode",
        "source": {
            "kind": "TrendsQuery",
            "series": [{"kind": "EventsNode", "event": event, "name": event, "math": "total"}],
            "dateRange": {"date_from": "-28d"},
            "interval": "day",
        },
    }


class Command(BaseCommand):
    help = "Seed events, dashboards, an annotation, and an errored alert for the Pulse eval corpus"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--skip-events", action="store_true", help="Only (re)create insights/dashboards/etc.")

    def handle(self, *args: Any, **options: Any) -> None:
        team = Team.objects.get(pk=options["team_id"])
        now = timezone.now()
        rng = random.Random(42)

        if not options["skip_events"]:
            total = 0
            for day_offset in range(DAYS, 0, -1):
                day = now - timedelta(days=day_offset)
                in_movement = day_offset <= MOVEMENT_DAYS_AGO
                for event, (base, movement_mult) in EVENTS.items():
                    count = int(base * (movement_mult if in_movement else 1.0) * rng.uniform(0.85, 1.15))
                    for _ in range(count):
                        create_event(
                            event_uuid=uuid.uuid4(),
                            event=event,
                            team=team,
                            distinct_id=f"pulse-eval-user-{rng.randrange(USERS)}",
                            timestamp=day + timedelta(seconds=rng.randrange(86400)),
                            properties={"$current_url": "https://app.example.com/subscriptions", "seed": "pulse-eval"},
                        )
                        total += 1
            for day_offset in (20, 11):
                create_event(
                    event_uuid=uuid.uuid4(),
                    event=SPARSE_EVENT,
                    team=team,
                    distinct_id="pulse-eval-user-0",
                    timestamp=now - timedelta(days=day_offset),
                    properties={"seed": "pulse-eval"},
                )
                total += 2
            self.stdout.write(f"Inserted ~{total} events across {DAYS} days (movement starts {MOVEMENT_DAYS_AGO}d ago)")

        dashboards: dict[str, list[str]] = {
            "Pulse eval: subscriptions": [
                "subscription_created",
                "subscription_delivered",
                "subscription_delivery_failed",
            ],
            "Pulse eval: web": ["$pageview"],
            "Pulse eval: flags": ["$feature_flag_called"],
            "Pulse eval: replay": ["recording_watched"],
            "Pulse eval: sparse": [SPARSE_EVENT],
        }
        goal_metric_short_id = None
        errored_alert_insight = None
        for name, events in dashboards.items():
            dashboard, _ = Dashboard.objects.get_or_create(
                team=team, name=name, defaults={"description": "pulse-eval seed"}
            )
            for event in events:
                insight, _ = Insight.objects.get_or_create(
                    team=team,
                    name=f"{event} (pulse eval)",
                    defaults={"query": _trends_query(event), "saved": True},
                )
                DashboardTile.objects.get_or_create(dashboard=dashboard, insight=insight)
                if event == "subscription_created":
                    goal_metric_short_id = insight.short_id
                if event == "subscription_delivered":
                    errored_alert_insight = insight
            self.stdout.write(f"Dashboard ready: {name} (id {dashboard.pk})")

        Annotation.objects.get_or_create(
            team=team,
            content="v2.4 deploy — delivery worker rollout (pulse-eval seed)",
            defaults={
                "date_marker": now - timedelta(days=MOVEMENT_DAYS_AGO),
                "organization": team.organization,
                "creation_type": "USR",
            },
        )
        self.stdout.write("Annotation created at the movement boundary (explain-stage candidate)")

        if errored_alert_insight is not None:
            alert, _ = AlertConfiguration.objects.get_or_create(
                team=team,
                name="Pulse eval: delivery volume alert",
                defaults={
                    "insight": errored_alert_insight,
                    "condition": {"type": "absolute_value"},
                    "config": {"type": "TrendsAlertConfig", "series_index": 0},
                    "state": AlertState.ERRORED,
                    "enabled": True,
                },
            )
            if alert.state != AlertState.ERRORED:
                alert.state = AlertState.ERRORED
                alert.save(update_fields=["state"])
            self.stdout.write("Errored alert in place (resource-health candidate)")

        self.stdout.write(self.style.SUCCESS("\nPulse eval corpus seeded. Config wiring:"))
        self.stdout.write(
            f"  eval:subscriptions-goal -> anchor 'Pulse eval: subscriptions', goal metric insight short_id: {goal_metric_short_id}"
        )
        self.stdout.write(
            "  eval:flags -> 'Pulse eval: flags' | eval:replay -> 'Pulse eval: replay' | eval:web-analytics -> 'Pulse eval: web'"
        )
        self.stdout.write("  eval:sparse -> 'Pulse eval: sparse' | eval:zero-config -> no anchors")
        self.stdout.write(
            "Re-run safe: events append (use --skip-events to avoid double volume); objects get_or_create."
        )
