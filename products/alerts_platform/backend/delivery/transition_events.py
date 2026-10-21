"""The `$alert_transition` event: one per announced transition, for a workflow to subscribe to.

The platform imports neither the product that produces internal events nor any source, so both
plug in here when Django starts:

- the product that owns alert destinations registers the producer;
- a source registers its facts, which carry the property names its own alert events used.

Imported from `ready()`, so it stays light: no models, no query layer, no transports.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import NAMESPACE_URL, uuid5

from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    AlertEventKind,
    AnnouncedTransition,
    EvaluationAnnouncement,
    SourceFacts,
    SourceKind,
    TransitionEvent,
    TransitionEventProducer,
)

# Whether the platform emits `$alert_transition` for a team's alerts. Read only where delivery
# already contacts the team's destinations, and a failed read emits nothing.
TRANSITION_EVENT_FLAG: Final = "alert-platform-transition-event"

_FAILURE_KINDS: Final = frozenset({AlertEventKind.ERRORED, AlertEventKind.BROKEN})

_producer: TransitionEventProducer | None = None
_source_facts: dict[SourceKind, SourceFacts] = {}


def register_producer(producer: TransitionEventProducer) -> None:
    global _producer
    if _producer is not None and _producer is not producer:
        raise RuntimeError("A different transition event producer is already registered.")
    _producer = producer


def register_source_facts(source: SourceKind, facts: SourceFacts) -> None:
    registered = _source_facts.get(source)
    if registered is not None and registered is not facts:
        raise RuntimeError(f"Different source facts are already registered for {source} alerts.")
    _source_facts[source] = facts


def producer() -> TransitionEventProducer:
    if _producer is None:
        raise RuntimeError("No transition event producer is registered.")
    return _producer


def transition_events(request: AlertDeliveryRequest, announced: EvaluationAnnouncement) -> list[TransitionEvent]:
    """One event per transition the evaluation announced.

    A source with no registered facts gets an empty `source` block, so its events still carry
    every platform field.
    """
    facts = _source_facts.get(request.source)
    return [
        TransitionEvent(
            properties=_properties(
                request,
                announced,
                transition,
                facts(request=request, announcement=announced, transition=transition) if facts is not None else {},
            ),
            timestamp=transition.occurred_at,
            uuid=_event_uuid(request, transition),
        )
        for transition in announced.transitions
    ]


def _properties(
    request: AlertDeliveryRequest,
    announced: EvaluationAnnouncement,
    transition: AnnouncedTransition,
    source_facts: dict[str, Any],
) -> dict[str, Any]:
    failed = transition.kind in _FAILURE_KINDS
    return {
        "alert_configuration_id": announced.configuration_id,
        "alert_name": announced.alert_name,
        "source_kind": announced.source.value,
        "transition": transition.kind.value,
        "occurred_at": transition.occurred_at.isoformat(),
        "episode_started_at": transition.episode_started_at.isoformat() if transition.episode_started_at else None,
        "value": transition.value,
        "labels": transition.labels,
        "grouping_key": transition.grouping_key,
        "error_message": transition.error_message if failed else None,
        "consecutive_failures": announced.consecutive_failures if failed else None,
        "url": request.source_alert_url or "",
        "source": source_facts,
    }


def _event_uuid(request: AlertDeliveryRequest, transition: AnnouncedTransition) -> str:
    # The occurrence is in the seed too, so two transitions recorded without an evaluation key keep distinct ids.
    seed = (
        f"{request.team_id}|{request.configuration_id}|{request.evaluation_key}|{transition.grouping_key}|"
        f"{transition.kind.value}|{transition.occurred_at.isoformat()}"
    )
    return str(uuid5(NAMESPACE_URL, seed))
