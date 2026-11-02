"""The `$insight_alert_firing` events the platform emits for an insight alert it owns on the HogFunction path.

The alert's HogFunctions filter on this event and render these properties, so the platform
reproduces what `trigger_alert_hog_functions` sends: the same names, read from the same alert,
with the breach text and chart URL the check recorded beside its verdict.

The insight stack emits no internal event for a failed check. It emails the subscribers only, and
native delivery already sends that, so an errored transition emits nothing here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final
from uuid import NAMESPACE_URL, uuid5

import structlog

from posthog.schema_enums import AlertState
from posthog.tasks.alerts.utils import RenderedInsightChart, detector_verdict_event_fields, insight_chart_url

from products.alerts.backend.facade.contracts import AlertInternalEvent
from products.alerts.backend.logic.destinations import emit_alert_internal_events
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.platform_alert_slack import insight_transition_properties
from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    AlertEventKind,
    AnnouncedTransition,
    EvaluationAnnouncement,
    LegacyEventEmission,
    MessageImage,
)
from products.cdp.backend.internal_events import LEGACY_INSIGHT_ALERT_EVENT

logger = structlog.get_logger(__name__)

# Below the delivery activity's own timeout, which a flush must not use up.
FLUSH_TIMEOUT_SECONDS: Final = 5.0


def emit_insight_legacy_events(
    *, request: AlertDeliveryRequest, announcement: EvaluationAnnouncement, emissions: Sequence[LegacyEventEmission]
) -> None:
    firings = [
        emission.transition
        for emission in emissions
        if emission.sends_message and emission.transition.kind == AlertEventKind.FIRING
    ]
    if not firings:
        return
    alert = (
        AlertConfiguration.objects.select_related("team", "insight")
        .filter(team_id=request.team_id, id=request.destination_alert_id)
        .first()
    )
    # A deleted alert takes its destinations with it, so nobody is left to receive the event.
    if alert is None:
        return
    emit_alert_internal_events(
        team_id=request.team_id,
        alert_id=request.destination_alert_id,
        events=[_firing_event(alert, transition) for transition in firings],
        flush_timeout_seconds=FLUSH_TIMEOUT_SECONDS,
    )


def insight_chart_url_of(team_id: int, source_detail: dict[str, Any]) -> str | None:
    """The URL that embeds the chart a check rendered, minted now from the ids the check stored."""
    asset_id = source_detail.get("insight_chart_asset_id")
    render_user_id = source_detail.get("insight_chart_render_user_id")
    if not isinstance(asset_id, int) or not isinstance(render_user_id, int):
        return None
    return insight_chart_url(
        team_id=team_id, chart=RenderedInsightChart(asset_id=asset_id, render_user_id=render_user_id)
    )


def insight_chart_image(*, team_id: int, transition: AnnouncedTransition) -> MessageImage | None:
    """The chart a native message shows for a firing, with its URL minted as the message goes out."""
    if transition.kind != AlertEventKind.FIRING:
        return None
    url = insight_chart_url_of(team_id, transition.source_detail)
    return MessageImage(url=url, alt_text="Insight chart") if url else None


def _formatting_properties(transition: AnnouncedTransition) -> dict[str, Any]:
    """The Slack card fields, or none of them.

    These enrich the event; the destinations it reaches do not depend on them. A stored detail the
    formatter cannot read must cost the firing its card, never its delivery.
    """
    try:
        return insight_transition_properties(transition)
    except Exception:
        logger.exception("alerts_insight_legacy_event_formatting_failed")
        return {}


def _firing_event(alert: AlertConfiguration, transition: AnnouncedTransition) -> AlertInternalEvent:
    detail = transition.source_detail
    properties: dict[str, Any] = {
        # From the transition, not the alert row: the platform never writes `state` or
        # `last_checked_at`, so a platform-owned alert past its shadow window would report the
        # frozen `not_firing` default on the very event that announces a firing.
        **alert.internal_event_properties(state=AlertState.FIRING.value, last_checked_at=transition.occurred_at),
        # Joined with newlines so each breach renders on its own line, as the insight stack sends it.
        "breaches": "\n".join(detail.get("breaches") or []),
        **detector_verdict_event_fields(detail.get("triggered_metadata")),
        **_formatting_properties(transition),
    }
    if chart_url := insight_chart_url_of(alert.team_id, detail):
        properties["insight_chart_url"] = chart_url
    # The occurrence is in the seed too, so two firings recorded without an evaluation key keep distinct ids.
    seed = (
        f"{alert.id}|{transition.grouping_key}|{LEGACY_INSIGHT_ALERT_EVENT}|{transition.evaluation_key}|"
        f"{transition.occurred_at.isoformat()}"
    )
    return AlertInternalEvent(
        event_name=LEGACY_INSIGHT_ALERT_EVENT,
        properties=properties,
        timestamp=transition.occurred_at,
        uuid=str(uuid5(NAMESPACE_URL, seed)),
    )
