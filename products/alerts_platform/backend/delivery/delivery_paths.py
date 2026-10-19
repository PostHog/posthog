"""Which path an alert the platform owns delivers through: native, or its source's HogFunctions.

Native delivery reproduces a stock destination only. A destination a person customized keeps
sending through its HogFunction, which the source feeds by emitting the internal events its own
stack emitted. Two products plug in here when Django starts, because the platform imports neither:

- the product that owns destinations registers the chooser, which reads them at send time;
- each source registers the emitter for its own events.

A source with no emitter delivers every alert natively.
"""

from __future__ import annotations

from collections.abc import Collection

import structlog

from products.alerts_platform.backend.facade.contracts import (
    DeliveryPath,
    DeliveryPathChooser,
    LegacyEventEmitter,
    SourceKind,
)

logger = structlog.get_logger(__name__)

_chooser: DeliveryPathChooser | None = None
_emitters: dict[SourceKind, LegacyEventEmitter] = {}


def register_chooser(chooser: DeliveryPathChooser) -> None:
    global _chooser
    if _chooser is not None and _chooser is not chooser:
        raise RuntimeError("A different delivery path chooser is already registered.")
    _chooser = chooser


def register_emitter(source: SourceKind, emitter: LegacyEventEmitter) -> None:
    registered = _emitters.get(source)
    if registered is not None and registered is not emitter:
        raise RuntimeError(f"A different legacy event emitter is already registered for {source} alerts.")
    _emitters[source] = emitter


def emitter_for(source: SourceKind) -> LegacyEventEmitter | None:
    return _emitters.get(source)


def choose_path(*, source: SourceKind, team_id: int, alert_id: str, allowed_event_ids: Collection[str]) -> DeliveryPath:
    """The path the alert's destinations allow now. Any failure takes the HogFunction path.

    The HogFunction path sends what the source's own stack sent, so it is the safe answer to doubt.
    Only a source with an emitter asks, so a missing chooser is doubt too.
    """
    if _chooser is None:
        logger.warning("alerts_platform_delivery_path_chooser_missing", team_id=team_id)
        return DeliveryPath.HOG_FUNCTION
    try:
        return _chooser(source=source, team_id=team_id, alert_id=alert_id, allowed_event_ids=allowed_event_ids)
    except Exception:
        logger.warning("alerts_platform_delivery_path_choice_failed", team_id=team_id, exc_info=True)
        return DeliveryPath.HOG_FUNCTION
