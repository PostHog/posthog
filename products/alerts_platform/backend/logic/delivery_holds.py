"""Deliveries a source held back, and the releases that decide whether they go out.

A source holds an evaluation's delivery while it works out whether the delivery should be sent,
for example while an agent investigates a firing. The platform knows nothing of why. It keeps the
request, hands it back to whoever releases it with a send, and sends it itself once the hold's
deadline passes, so a source that never answers still delivers.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Final

from django.db import transaction

from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    HeldDeliveryAddress,
    PlatformAlertOutcome,
)
from products.alerts_platform.backend.facade.enums import HoldRelease, HoldReleasedBy
from products.alerts_platform.backend.models import PlatformAlertConfiguration, PlatformAlertDeliveryHold
from products.alerts_platform.backend.models.platform_alert_events_sql import PLATFORM_ALERT_EVENTS_TTL_DAYS

# As long as the history rows a hold annotates live, so a reader never finds one without the other.
HOLD_RETENTION: Final = timedelta(days=PLATFORM_ALERT_EVENTS_TTL_DAYS)


def hold_for(
    configuration: PlatformAlertConfiguration, outcome: PlatformAlertOutcome, now: datetime
) -> PlatformAlertDeliveryHold | None:
    """The hold an outcome asks for, unsaved, so `record_outcomes` writes it in its own transaction."""
    held = outcome.held_delivery
    if held is None:
        return None
    return PlatformAlertDeliveryHold(
        team_id=configuration.team_id,
        configuration_id=configuration.id,
        evaluation_key=outcome.evaluation_key,
        reason=held.reason,
        request=held.request.to_stored(),
        held_at=now,
        release_after=now + timedelta(seconds=held.release_after_seconds),
    )


def release_hold(
    address: HeldDeliveryAddress, *, action: HoldRelease, released_by: HoldReleasedBy, now: datetime
) -> AlertDeliveryRequest | None:
    """Releases one hold. Returns the request when the caller should start its delivery.

    The first release wins. A later one changes nothing and gets the request back only when it
    repeats the winning send from the same releaser, which is a retry of a caller that committed
    the release and failed before it started the delivery. The delivery's id then dedups it.
    """
    with transaction.atomic():
        hold = (
            PlatformAlertDeliveryHold.objects.for_team(address.team_id)
            .select_for_update()
            .filter(configuration_id=address.configuration_id, evaluation_key=address.evaluation_key)
            .first()
        )
        if hold is None:
            return None
        if hold.released_at is not None:
            repeated = hold.release_action == action == HoldRelease.SEND and hold.released_by == released_by
            return AlertDeliveryRequest.from_stored(hold.request) if repeated else None
        hold.released_at = now
        hold.release_action = action.value
        hold.released_by = released_by.value
        hold.save(update_fields=["released_at", "release_action", "released_by"])
    return AlertDeliveryRequest.from_stored(hold.request) if action == HoldRelease.SEND else None


def reschedule_hold(address: HeldDeliveryAddress, *, release_after: datetime) -> bool:
    """Moves an unreleased hold's deadline. Returns False when the hold is gone or already released.

    A source calls this in the transaction that records why it has not released yet, so the
    deadline cannot pass between the two.
    """
    updated = (
        PlatformAlertDeliveryHold.objects.for_team(address.team_id)
        .filter(
            configuration_id=address.configuration_id,
            evaluation_key=address.evaluation_key,
            released_at__isnull=True,
        )
        .update(release_after=release_after)
    )
    return updated > 0


def blocks_delivery(team_id: int, configuration_id: str, evaluation_key: str) -> bool:
    """Whether an evaluation has a hold that is not released with a send.

    A second guard behind the source, which leaves a held request out of the deliveries it starts.
    """
    return (
        PlatformAlertDeliveryHold.objects.for_team(team_id)
        .filter(configuration_id=configuration_id, evaluation_key=evaluation_key)
        # An unreleased hold has no action, and the exclusion keeps it.
        .exclude(release_action=HoldRelease.SEND)
        .exists()
    )


def prune_holds(now: datetime, *, limit: int) -> int:
    """Deletes up to `limit` holds older than the history rows they annotate. Returns how many."""
    stale = list(
        PlatformAlertDeliveryHold.objects.unscoped()
        .filter(held_at__lt=now - HOLD_RETENTION)
        .values_list("id", flat=True)[:limit]
    )
    return PlatformAlertDeliveryHold.objects.unscoped().filter(id__in=stale).delete()[0] if stale else 0


def expired_holds(now: datetime, *, limit: int) -> tuple[HeldDeliveryAddress, ...]:
    """The holds past their deadline, oldest first.

    Every team's, so one sweep covers the fleet. A disabled configuration's holds are left held,
    the way the source's own safety net skips a disabled alert. An alert rolled back to its source
    is still swept, because its held request was decided while the platform owned it.
    """
    rows = (
        PlatformAlertDeliveryHold.objects.unscoped()
        .filter(released_at__isnull=True, release_after__lte=now, configuration__enabled=True)
        .order_by("release_after")
        .values_list("team_id", "configuration_id", "evaluation_key")[:limit]
    )
    return tuple(
        HeldDeliveryAddress(team_id=team_id, configuration_id=str(configuration_id), evaluation_key=key)
        for team_id, configuration_id, key in rows
    )


def release_expired(addresses: Sequence[HeldDeliveryAddress], now: datetime) -> tuple[AlertDeliveryRequest, ...]:
    """Releases each hold with a send from the safety net, and returns the requests it won.

    One transaction per hold, so a hold another releaser locked delays only itself.
    """
    released = (
        release_hold(address, action=HoldRelease.SEND, released_by=HoldReleasedBy.SAFETY_NET, now=now)
        for address in addresses
    )
    return tuple(request for request in released if request is not None)
