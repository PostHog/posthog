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

from posthog.dataclasses import frozen

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
# A releaser starts its delivery seconds after the release. One that has not started by then failed
# between the two, and the sweep starts it instead.
START_GRACE: Final = timedelta(minutes=5)


@frozen
class SweptHolds:
    """The requests a sweep starts, and which of them it released at their deadline just now."""

    requests: tuple[AlertDeliveryRequest, ...]
    expired: tuple[AlertDeliveryRequest, ...]


@frozen
class HoldSweep:
    """What one sweep found to send: holds past their deadline, and released sends nobody started."""

    expired: tuple[HeldDeliveryAddress, ...]
    unstarted: tuple[HeldDeliveryAddress, ...]


def _address(team_id: int, configuration_id: object, evaluation_key: str) -> HeldDeliveryAddress:
    return HeldDeliveryAddress(team_id=team_id, configuration_id=str(configuration_id), evaluation_key=evaluation_key)


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
    request, _ = _release(address, action=action, released_by=released_by, now=now, by_safety_net=False)
    return request


def _release(
    address: HeldDeliveryAddress,
    *,
    action: HoldRelease,
    released_by: HoldReleasedBy,
    now: datetime,
    by_safety_net: bool,
) -> tuple[AlertDeliveryRequest | None, bool]:
    """`release_hold`, plus whether this call made the release.

    The safety net skips a hold another transaction has locked, so a slow source delays only its
    own hold, and a later sweep finds it again. It re-reads the deadline under the lock, so a hold
    rescheduled after the sweep found it stays held. It suppresses, rather than sends, the hold of a
    configuration that is disabled by then, so turning the alert back on never sends a firing that old.
    """
    with transaction.atomic():
        hold = (
            PlatformAlertDeliveryHold.objects.for_team(address.team_id)
            .select_related("configuration")
            .select_for_update(of=("self",), skip_locked=by_safety_net)
            .filter(configuration_id=address.configuration_id, evaluation_key=address.evaluation_key)
            .first()
        )
        if hold is None:
            return None, False
        if hold.released_at is not None:
            repeated = hold.release_action == action == HoldRelease.SEND and hold.released_by == released_by
            return (AlertDeliveryRequest.from_stored(hold.request) if repeated else None), False
        if by_safety_net and hold.release_after > now:
            return None, False
        if by_safety_net and not hold.configuration.enabled:
            action = HoldRelease.SUPPRESS
        hold.released_at = now
        hold.release_action = action.value
        hold.released_by = released_by.value
        hold.save(update_fields=["released_at", "release_action", "released_by"])
    return (AlertDeliveryRequest.from_stored(hold.request) if action == HoldRelease.SEND else None), True


def record_delivery_started(addresses: Sequence[HeldDeliveryAddress], now: datetime) -> None:
    """Marks released sends whose delivery a caller started, so the sweep does not start them again."""
    for address in addresses:
        PlatformAlertDeliveryHold.objects.for_team(address.team_id).filter(
            configuration_id=address.configuration_id,
            evaluation_key=address.evaluation_key,
            release_action=HoldRelease.SEND,
            delivery_started_at__isnull=True,
        ).update(delivery_started_at=now)


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
    if not stale:
        return 0
    # nosemgrep: idor-lookup-without-team — fleet-wide retention prune by age; no request or team input reaches it
    return PlatformAlertDeliveryHold.objects.unscoped().filter(id__in=stale).delete()[0]


def holds_to_send(now: datetime, *, limit: int) -> HoldSweep:
    """The holds the safety net sends now, oldest first, up to `limit` of each kind.

    Every team's, so one sweep covers the fleet. A disabled configuration's holds are found too, and
    suppressed when released. An alert rolled back to its source is still swept, because its held
    request was decided while the platform owned it.
    """
    expired = (
        PlatformAlertDeliveryHold.objects.unscoped()
        .filter(released_at__isnull=True, release_after__lte=now)
        .order_by("release_after")
        .values_list("team_id", "configuration_id", "evaluation_key")[:limit]
    )
    unstarted = (
        PlatformAlertDeliveryHold.objects.unscoped()
        .filter(
            release_action=HoldRelease.SEND,
            delivery_started_at__isnull=True,
            released_at__lte=now - START_GRACE,
        )
        .order_by("released_at")
        .values_list("team_id", "configuration_id", "evaluation_key")[:limit]
    )
    return HoldSweep(
        expired=tuple(_address(*row) for row in expired), unstarted=tuple(_address(*row) for row in unstarted)
    )


def _stored_request(address: HeldDeliveryAddress) -> AlertDeliveryRequest | None:
    stored = (
        PlatformAlertDeliveryHold.objects.for_team(address.team_id)
        .filter(configuration_id=address.configuration_id, evaluation_key=address.evaluation_key)
        .values_list("request", flat=True)
        .first()
    )
    return None if stored is None else AlertDeliveryRequest.from_stored(stored)


def send_swept(sweep: HoldSweep, now: datetime, *, max_bytes: int) -> SweptHolds:
    """The requests the sweep starts: released sends nobody started, then expired holds it releases.

    Stops before the requests outgrow `max_bytes`, because they return through one activity result.
    A hold left out stays as it was, so the next sweep finds it again. Each expired hold is released
    in a transaction of its own, so a hold another releaser locked delays only itself.
    """
    # Deferred: the payload helper imports temporalio, which must stay off django.setup().
    from products.alerts_platform.backend.facade.payload import payload_bytes  # noqa: PLC0415

    requests: list[AlertDeliveryRequest] = []
    expired: list[AlertDeliveryRequest] = []
    spent = 0
    for address in (*sweep.unstarted, *sweep.expired):
        request = _stored_request(address)
        if request is None:
            continue
        size = payload_bytes(request)
        if requests and spent + size > max_bytes:
            break
        if address in sweep.expired:
            released, fresh = _release(
                address, action=HoldRelease.SEND, released_by=HoldReleasedBy.SAFETY_NET, now=now, by_safety_net=True
            )
            if released is None:
                continue
            if fresh:
                expired.append(released)
            request = released
        requests.append(request)
        spent += size
    return SweptHolds(requests=tuple(requests), expired=tuple(expired))
