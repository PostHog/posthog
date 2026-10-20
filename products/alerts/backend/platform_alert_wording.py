"""The insight wording of a native message for an insight alert the platform delivers.

The platform alone can say only "Value: 150". The insight stack says which threshold the insight
crossed, names the insight, and links to it. The check records those beside its verdict, so the
describer reads them from the transition and does no I/O, as the platform requires.

Imported from `ready()`, so it stays light: no models, no query layer.
"""

from __future__ import annotations

from posthog.utils import absolute_uri

from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    AnnouncedTransition,
    MessageDetail,
    MessageLink,
    SourceDescription,
)


def describe_insight_transition(*, project_id: int, transition: AnnouncedTransition) -> SourceDescription:
    detail = transition.source_detail
    breaches = (detail.get("breaches") or []) if transition.kind == AlertEventKind.FIRING else []
    insight_name = detail.get("insight_name")
    insight_short_id = detail.get("insight_short_id")
    return SourceDescription(
        details=tuple(MessageDetail(label="Threshold breached", value=breach) for breach in breaches),
        context=(f"Insight: {insight_name}",) if insight_name else (),
        data_link=MessageLink(label="View insight", url=insight_url(project_id, insight_short_id))
        if insight_short_id
        else None,
    )


def insight_url(project_id: int, insight_short_id: str) -> str:
    return absolute_uri(f"/project/{project_id}/insights/{insight_short_id}")


def insight_alert_url(project_id: int, insight_short_id: str, alert_id: str) -> str:
    """The alert's page on its insight, which the insight stack's messages link to."""
    return absolute_uri(f"/project/{project_id}/insights/{insight_short_id}/alerts?alert_id={alert_id}")
