import re

from products.alerts.backend.facade.api import list_firing_alerts_created_by, list_firing_alerts_for_project
from products.alerts.backend.facade.contracts import FiringAlert, ProjectFiringAlert
from products.today.backend.facade.contracts import (
    HighlightCandidate,
    HighlightContext,
    HighlightFindings,
    NewsContext,
    NewsFact,
)
from products.today.backend.facade.enums import HighlightLabel, NewsTone
from products.today.backend.facade.highlight_helpers import short

ALERT_FIRING = "Alert ‘{alert}’ is firing"
UNNAMED_ALERT_FIRING = "An alert is firing"
ALERT_FIRING_DETAIL = "Insight ‘{insight}’"


def _candidate(alert: FiringAlert) -> HighlightCandidate:
    name = re.sub(r"(?i)\s+alert$", "", short(alert.name))
    return HighlightCandidate(
        key=f"alert:{alert.id}",
        label=HighlightLabel.RISK,
        family="alerts",
        importance=0.85,
        relevance=1.0,
        title=ALERT_FIRING.format(alert=name) if name else UNNAMED_ALERT_FIRING,
        detail=ALERT_FIRING_DETAIL.format(insight=short(alert.insight_name or alert.insight_short_id)),
        url=f"/insights/{alert.insight_short_id}",
        ref=alert.insight_short_id,
    )


def find_firing_alerts(context: HighlightContext) -> HighlightFindings:
    alerts = list_firing_alerts_created_by(
        context.team, context.user, include_metrics_insights=context.allows("metrics:read"), limit=10
    )
    return HighlightFindings(items=tuple(_candidate(alert) for alert in alerts))


NEWS_ALERT_LIMIT = 10
SHARED_ALERT_SUBSCRIBERS = 2


def _news_fact(alert: ProjectFiringAlert, context: NewsContext) -> NewsFact:
    return NewsFact(
        key=f"alert:{alert.id}",
        kind="alert_firing",
        title=re.sub(r"(?i)\s+alert$", "", short(alert.name)) or short(alert.insight_name or alert.insight_short_id),
        importance=0.85,
        magnitude=1.0,
        breadth=1.0 if alert.subscriber_count >= SHARED_ALERT_SUBSCRIBERS else 0.7,
        at=alert.last_notified_at or context.end,
        tone=NewsTone.RISK,
        resource="insight",
        scopes=("alert:read", "insight:read"),
        object_id=str(alert.insight_id),
        numbers={"insight": short(alert.insight_name or alert.insight_short_id), "subscribers": alert.subscriber_count},
        url=f"/insights/{alert.insight_short_id}",
    )


def find_firing_alert_news(context: NewsContext) -> tuple[NewsFact, ...]:
    if not context.shared("alert") or not context.shared("insight"):
        return ()
    alerts = list_firing_alerts_for_project(
        team_id=context.team.id, withheld_insight_ids=context.withheld("insight"), limit=NEWS_ALERT_LIMIT
    )
    return tuple(_news_fact(alert, context) for alert in alerts)
