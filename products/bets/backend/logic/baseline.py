from datetime import datetime, timedelta

from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.product_analytics.backend.facade.api import saved_insight_for_read
from products.product_analytics.backend.facade.measurement import insight_delivery_evidence

from ..models import Bet
from .metrics import metric, observed, refresh_metrics, tracked_before_window
from .plan import MIN_DAYS, readiness

FRESH_WITHIN = timedelta(hours=24)


@frozen
class Baseline:
    ready: bool
    value: float | None
    note: str


def result(ready: bool, value: float | None, note: str) -> Baseline:
    return Baseline(ready=ready, value=value, note=note)


def event_names(node: object) -> set[str]:
    if isinstance(node, dict):
        own = {str(node["event"])} if node.get("kind") == "EventsNode" and node.get("event") else set()
        return own | {name for value in node.values() for name in event_names(value)}
    if isinstance(node, list):
        return {name for value in node for name in event_names(value)}
    return set()


def baseline(team: Team, user: User, bet: Bet, *, since: datetime | None = None) -> Baseline:
    if not bet.goal_insight:
        return result(False, None, "Waiting for a saved insight that measures the goal.")
    insight = saved_insight_for_read(team=team, user=user, short_id=bet.goal_insight)
    if insight is None:
        return result(False, None, "The goal insight is not accessible to the bet owner.")
    refresh_metrics(team, user, [bet.goal_insight])
    current = metric(team, user, bet.goal_insight)
    delivery = insight_delivery_evidence(team=team, user=user, short_id=bet.goal_insight)
    missing = event_names(insight.query) - set(delivery.event_names if delivery else ())
    if missing:
        return result(False, current.current, f"Waiting for events: {', '.join(sorted(missing))}.")
    last = delivery.last_event_at if delivery else None
    if last is None or last < timezone.now() - FRESH_WITHIN or (since is not None and last < since):
        return result(False, current.current, "Waiting for fresh events.")
    if current.current is None:
        return result(False, None, current.message or "Waiting for a value.")
    people, days = observed(team, user, bet.goal_insight)
    if tracked_before_window(team, user, bet.goal_insight):
        days = max(days, MIN_DAYS)
    ready = readiness(people, days)
    if not ready.ready:
        return result(False, current.current, ready.note)
    return result(True, current.current, "")
