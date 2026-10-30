"""Whether native delivery may send an alert's destinations, or they keep sending through HogFunctions.

Native delivery reproduces a stock destination only. Every other destination keeps its HogFunction,
which sends exactly what it sent before the cutover. The answer covers every destination of the
alert, disabled ones too, because a person can enable one in the middle of a firing.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from functools import cached_property

import structlog

from posthog.models import Team

from products.alerts.backend.facade.contracts import (
    DeliveryPathChoice,
    DestinationBucket,
    DestinationEligibility,
    HogFunctionPathReason,
)
from products.alerts.backend.logic.destination_configs import PagerDutyDestination, WebhookDestination
from products.alerts.backend.logic.destination_eligibility import (
    bucket_for,
    classify_alert_destinations,
    classify_destinations_by_alert,
    unbound_alert_destinations,
)
from products.alerts_platform.backend.facade.contracts import DeliveryPath, SourceKind
from products.alerts_platform.backend.facade.delivery import native_sends_legacy_webhook_body

logger = structlog.get_logger(__name__)


def delivery_path(
    *, source: SourceKind, team_id: int, alert_id: str, allowed_event_ids: Collection[str]
) -> DeliveryPath:
    """The platform's chooser: the path one alert's destinations allow now."""
    team = _TeamDestinations(source=source, team_id=team_id, allowed_event_ids=allowed_event_ids)
    choice = team.unbound_choice() or team.choice(
        classify_alert_destinations(team_id=team_id, alert_id=alert_id, allowed_event_ids=allowed_event_ids)
    )
    if choice.reason is not None:
        logger.info("alert_delivery_path_hog_function", team_id=team_id, alert_id=alert_id, reason=choice.reason)
    return choice.path


def team_delivery_paths(
    *, source: SourceKind, team_id: int, alert_ids: Sequence[str], allowed_event_ids: Collection[str]
) -> dict[str, DeliveryPathChoice]:
    """The path each alert of one team would take now, read with one lookup per kind for the whole team."""
    team = _TeamDestinations(source=source, team_id=team_id, allowed_event_ids=allowed_event_ids)
    if (unbound := team.unbound_choice()) is not None:
        return dict.fromkeys(alert_ids, unbound)
    by_alert = classify_destinations_by_alert(team_id=team_id, alert_ids=alert_ids, allowed_event_ids=allowed_event_ids)
    return {alert_id: team.choice(destinations) for alert_id, destinations in by_alert.items()}


class _TeamDestinations:
    """What every alert of one team shares: its unbound functions and its webhook body."""

    def __init__(self, *, source: SourceKind, team_id: int, allowed_event_ids: Collection[str]) -> None:
        self._source = source
        self._team_id = team_id
        self._allowed_event_ids = allowed_event_ids

    def unbound_choice(self) -> DeliveryPathChoice | None:
        """Every alert of a team with an unbound function sends through HogFunctions, whatever its own destinations are."""
        return DeliveryPathChoice(reason=HogFunctionPathReason.UNBOUND) if self._has_unbound else None

    def choice(self, destinations: Sequence[DestinationEligibility]) -> DeliveryPathChoice:
        if any(bucket_for(destination) != DestinationBucket.STOCK for destination in destinations):
            return DeliveryPathChoice(reason=HogFunctionPathReason.CUSTOMIZED)
        # Per alert, so the team's other alerts still deliver natively.
        if self._source == SourceKind.INSIGHT and any(
            destination.template_id == PagerDutyDestination.template_id for destination in destinations
        ):
            return DeliveryPathChoice(reason=HogFunctionPathReason.PAGERDUTY_NOT_NATIVE)
        if any(destination.template_id == WebhookDestination.template_id for destination in destinations):
            if self._native_webhook_body is None:
                return DeliveryPathChoice(reason=HogFunctionPathReason.WEBHOOK_BODY_UNKNOWN)
            if not self._native_webhook_body:
                return DeliveryPathChoice(reason=HogFunctionPathReason.NEW_WEBHOOK_BODY)
        return DeliveryPathChoice()

    @cached_property
    def _has_unbound(self) -> bool:
        return bool(
            unbound_alert_destinations(
                team_id=self._team_id, allowed_event_ids=self._allowed_event_ids, include_disabled=True
            )
        )

    @cached_property
    def _native_webhook_body(self) -> bool | None:
        return native_sends_legacy_webhook_body(self._source, Team.objects.get(id=self._team_id))
