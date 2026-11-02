import re

from products.alerts.backend.facade.api import list_firing_alerts_created_by
from products.alerts.backend.facade.contracts import FiringAlert
from products.today.backend.facade.contracts import HighlightCandidate, HighlightContext, HighlightFindings
from products.today.backend.facade.enums import HighlightLabel
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
