"""The insight wording of a native message for an insight alert the platform delivers.

The platform alone can say only "Value: 150". The insight stack says which threshold the insight
crossed, names the insight, and links to it. The check records those beside its verdict, so the
describer reads them from the transition and does no I/O, as the platform requires.

Imported from `ready()`, so it stays light: no models, no query layer.
"""

from __future__ import annotations

from typing import Final

from posthog.utils import absolute_uri

from products.alerts.backend.logic.insight_alert_destinations import snooze_select
from products.alerts_platform.backend.facade.contracts import (
    SOURCE_CONDITION_KEY,
    AlertEventKind,
    AnnouncedTransition,
    MessageDetail,
    MessageLink,
    SourceDescription,
)

# The platform kind of the follow-up sent when an investigation's verdict contradicts the previous
# verdict of the same firing.
VERDICT_CHANGED_KIND: Final = "verdict_changed"


def announces_firing(transition: AnnouncedTransition) -> bool:
    """Whether a transition is worded as a firing: the firing itself, or a follow-up to its verdict."""
    return transition.kind in (AlertEventKind.FIRING, VERDICT_CHANGED_KIND)


def describe_insight_transition(*, project_id: int, transition: AnnouncedTransition) -> SourceDescription:
    detail = transition.source_detail
    # A failure keeps the platform's own wording, so only a firing states breaches or offers a snooze.
    firing = announces_firing(transition)
    breaches = _firing_breaches(project_id, transition) if firing else []
    alert_id = detail.get("alert_id") if firing else None
    insight_name = detail.get("insight_name")
    insight_short_id = detail.get("insight_short_id")
    return SourceDescription(
        # One detail for every breach, because a transport such as PagerDuty keys its details by label.
        details=(MessageDetail(label=_breach_label(transition), value="\n".join(breaches)),) if breaches else (),
        context=(f"Insight: {insight_name}",) if insight_name else (),
        data_link=MessageLink(label="View insight", url=insight_url(project_id, insight_short_id))
        if insight_short_id
        else None,
        slack_elements=(snooze_select(alert_id),) if alert_id else (),
    )


def _firing_breaches(project_id: int, transition: AnnouncedTransition) -> list[str]:
    from products.alerts.backend.platform_investigation_message import (  # noqa: PLC0415 - keeps models off the startup path
        firing_breaches,
        firing_investigation,
    )

    # The platform passes the team's id as the project id.
    return firing_breaches(transition, firing_investigation(project_id, transition))


def _breach_label(transition: AnnouncedTransition) -> str:
    condition = transition.source_config.get(SOURCE_CONDITION_KEY)
    return "Anomaly detected" if isinstance(condition, dict) and condition.get("detector") else "Threshold breached"


def insight_url(project_id: int, insight_short_id: str) -> str:
    return absolute_uri(f"/project/{project_id}/insights/{insight_short_id}")


def insight_alert_url(project_id: int, insight_short_id: str, alert_id: str) -> str:
    """The alert's page on its insight, which the insight stack's messages link to."""
    return absolute_uri(f"/project/{project_id}/insights/{insight_short_id}/alerts?alert_id={alert_id}")
