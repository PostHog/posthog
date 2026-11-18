"""What the investigation agent writes back for a platform evaluation of an insight alert.

The agent records its status and verdict on the `InsightAlertInvestigation` row, and releases the
firing's held delivery by the verdict. Kept apart from the decision and claim, which read the
insight stack's rules from `posthog.temporal.alerts`, because that package imports the agent.
"""

from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from django.db import transaction

import structlog

from posthog.tasks.alerts.investigation_notifications import (
    INVESTIGATION_NOTIFY_GRACE_MINUTES,
    INVESTIGATION_RUNNING_GRACE_MINUTES,
)
from posthog.tasks.alerts.utils import _inconclusive_is_suppressed, _should_suppress_notification

from products.alerts.backend.facade.contracts import InvestigationRelease
from products.alerts.backend.models.alert import AlertConfiguration, InvestigationStatus
from products.alerts.backend.models.investigation import InsightAlertInvestigation
from products.alerts_platform.backend.facade import api as platform
from products.alerts_platform.backend.facade.contracts import AlertDeliveryRequest, HeldDeliveryAddress
from products.alerts_platform.backend.facade.enums import HoldRelease, HoldReleasedBy

logger = structlog.get_logger(__name__)

# The insight stack's safety-net graces: a running investigation holds its firing this long after
# the check, and a finished one this long after it finished.
RUNNING_HOLD: Final = timedelta(minutes=INVESTIGATION_RUNNING_GRACE_MINUTES)
TERMINAL_HOLD: Final = timedelta(minutes=INVESTIGATION_NOTIFY_GRACE_MINUTES)


def earlier_in_episode(
    team_id: int, configuration_id: UUID, episode_started_at: datetime | None, evaluation_key: str
) -> list[tuple[str, str | None]]:
    """Status and verdict of the firing's other investigations, newest first. One read, because a
    firing holds a few rows. Its own row is left out, because a retry can find it already written."""
    return list(
        InsightAlertInvestigation.objects.for_team(team_id)
        .filter(configuration_id=configuration_id, episode_started_at=episode_started_at)
        .exclude(evaluation_key=evaluation_key)
        .order_by("-created_at")
        .values_list("status", "verdict")
    )


def last_verdict(earlier: list[tuple[str, str | None]]) -> str | None:
    return next((verdict for _, verdict in earlier if verdict is not None), None)


def previous_verdict_in_episode(
    team_id: int, configuration_id: UUID, episode_started_at: datetime | None, evaluation_key: str
) -> str | None:
    """The last verdict another investigation of the same firing reached."""
    return last_verdict(earlier_in_episode(team_id, configuration_id, episode_started_at, evaluation_key))


def verdict_change_is_news(verdict: str | None, previous_verdict: str | None, inconclusive_action: str | None) -> bool:
    """Whether a verdict that differs from the firing's previous one earns a follow-up on a firing that
    already went out. A change to a false positive is sent, because it corrects what the user already
    read. An inconclusive verdict still follows the alert's policy."""
    if not previous_verdict or verdict == previous_verdict:
        return False
    return not _inconclusive_is_suppressed(verdict, inconclusive_action)


def release_held(
    address: HeldDeliveryAddress, *, suppress: bool, released_by: HoldReleasedBy
) -> AlertDeliveryRequest | None:
    """Releases a held firing. Returns the request the caller starts when it goes out. A retry from the
    same releaser gets the same request back, so it can start a delivery the first attempt did not."""
    return platform.release_hold(
        address,
        action=HoldRelease.SUPPRESS if suppress else HoldRelease.SEND,
        released_by=released_by,
        now=datetime.now(UTC),
    )


def _hold_of(investigation: InsightAlertInvestigation) -> HeldDeliveryAddress:
    return HeldDeliveryAddress(
        team_id=investigation.team_id,
        configuration_id=str(investigation.configuration_id),
        evaluation_key=investigation.evaluation_key,
    )


def mark_investigation_running(investigation: InsightAlertInvestigation) -> None:
    """Marks the investigation as running, and holds its firing for the running grace again, because
    a retry after a failure would otherwise run on the failure's short grace."""
    with transaction.atomic():
        InsightAlertInvestigation.objects.for_team(investigation.team_id).filter(id=investigation.id).update(
            status=InvestigationStatus.RUNNING
        )
        platform.reschedule_hold(_hold_of(investigation), release_after=investigation.created_at + RUNNING_HOLD)


def mark_investigation_failed(investigation: InsightAlertInvestigation, reason: str) -> None:
    """Records the failure, and leaves the firing to the safety net after the terminal grace, as the
    insight stack sends a firing whose investigation failed."""
    with transaction.atomic():
        InsightAlertInvestigation.objects.for_team(investigation.team_id).filter(id=investigation.id).update(
            status=InvestigationStatus.FAILED, error={"message": reason}
        )
        platform.reschedule_hold(_hold_of(investigation), release_after=datetime.now(UTC) + TERMINAL_HOLD)


def finish_investigation(
    alert: AlertConfiguration,
    investigation: InsightAlertInvestigation,
    *,
    verdict: str | None,
    summary: str | None,
    notebook_id: UUID | None,
) -> InvestigationRelease:
    """Records the verdict and releases the firing's held delivery by it, in one transaction, so the
    safety net can never find a recorded verdict with its firing still held. A firing that already
    went out gets a verdict-changed announcement when its verdict contradicts the firing's previous one.

    Safe to repeat for a recorded verdict: a retry gets back what the first call released.
    """
    previous_verdict = previous_verdict_in_episode(
        investigation.team_id,
        investigation.configuration_id,
        investigation.episode_started_at,
        investigation.evaluation_key,
    )
    verdict_suppresses = _should_suppress_notification(verdict, alert.investigation_inconclusive_action)
    with transaction.atomic():
        InsightAlertInvestigation.objects.for_team(investigation.team_id).filter(id=investigation.id).update(
            status=InvestigationStatus.DONE, verdict=verdict, summary=summary, notebook_id=notebook_id, error=None
        )
        delivery = release_held(
            _hold_of(investigation),
            # As the safety net does, so turning the alert back on never sends a firing that old.
            suppress=not alert.enabled or verdict_suppresses,
            # A firing only the disabled alert holds back is the safety net's suppress, so history does
            # not show it as the agent's.
            released_by=HoldReleasedBy.VERDICT if verdict_suppresses or alert.enabled else HoldReleasedBy.SAFETY_NET,
        )
    if delivery is None:
        delivery = _announce_verdict_change(alert, investigation, verdict=verdict, previous_verdict=previous_verdict)
    return InvestigationRelease(deliveries=(delivery,) if delivery else (), previous_verdict=previous_verdict)


def _announce_verdict_change(
    alert: AlertConfiguration,
    investigation: InsightAlertInvestigation,
    *,
    verdict: str | None,
    previous_verdict: str | None,
) -> AlertDeliveryRequest | None:
    """The insight stack's verdict-change follow-up, for a firing whose delivery already went out."""
    if not verdict_change_is_news(verdict, previous_verdict, alert.investigation_inconclusive_action):
        return None
    address = _hold_of(investigation)
    if platform.delivery_held_back(address):
        # The firing was suppressed, or the safety net has not sent it yet, so the user read no verdict.
        return None
    logger.info(
        "insight_alert_investigation.verdict_changed",
        alert_id=str(alert.id),
        investigation_id=str(investigation.id),
        verdict=verdict,
        previous_verdict=previous_verdict,
    )
    return platform.record_verdict_changed(
        address, episode_started_at=investigation.episode_started_at, now=datetime.now(UTC)
    )
