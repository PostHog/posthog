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

from posthog.schema_enums import AlertState

from products.alerts.backend.facade.contracts import AlertInternalEvent
from products.alerts.backend.logic.destinations import emit_alert_internal_events
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    AlertEventKind,
    AnnouncedTransition,
    EvaluationAnnouncement,
    LegacyEventEmission,
)
from products.cdp.backend.internal_events import LEGACY_INSIGHT_ALERT_EVENT

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


def _firing_event(alert: AlertConfiguration, transition: AnnouncedTransition) -> AlertInternalEvent:
    detail = transition.source_detail
    properties: dict[str, Any] = {
        **alert.internal_event_properties(state=AlertState.FIRING.value, last_checked_at=transition.occurred_at),
        "breaches": "\n".join(detail.get("breaches") or []),
    }
    if detail.get("insight_chart_url"):
        properties["insight_chart_url"] = detail["insight_chart_url"]
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
