"""Investigation-agent trigger helpers used by the Temporal evaluate_alert activity.

The trigger and notification-gating decisions both run inside `evaluate_alert`
in the same DB transaction as the AlertCheck insert, so the read-then-write that
claims the cooldown lease stays consistent. This module exposes the primitives
as pure functions so they can be unit-tested independently of Temporal.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from django.db.models import Q

from posthog.schema import AlertCalculationInterval, AlertState

from posthog.dataclasses import frozen
from posthog.tasks.alerts.investigation_notifications import INVESTIGATION_RUNNING_GRACE_MINUTES
from posthog.tasks.alerts.utils import _should_suppress_notification

from products.alerts.backend.investigation_episode import episode_investigations
from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration, InvestigationStatus

# A firing episode is the run of consecutive FIRING checks since the last check that was
# not FIRING. Every check in the episode is eligible, up to this many investigations, so
# a verdict that flips halfway through an incident still gets found. The budget is the
# only cap: dismissals and confirmations spend it alike.
MAX_INVESTIGATIONS_PER_EPISODE = 3

# The cooldown only stops an alert that flaps inside one of its own intervals. It must
# stay below the interval, or scheduler jitter decides whether the next scheduled check
# investigates. Long intervals keep the historical one-hour ceiling.
INVESTIGATION_COOLDOWN_MARGIN = timedelta(minutes=5)
MAX_INVESTIGATION_COOLDOWN = timedelta(hours=1)
MIN_INVESTIGATION_COOLDOWN = timedelta(minutes=5)

# An investigation that is still in flight blocks a new one however long it has run. The
# cooldown is shorter than the alert's interval by design, so on a fast cadence the previous
# check falls outside the cooldown window while its agent still works, and a purely
# time-scoped guard would let two agents investigate the same anomaly at once. Past this
# horizon the row is presumed dead, which is the same point at which the notification safety
# net stops waiting for a non-terminal investigation.
IN_FLIGHT_INVESTIGATION_HORIZON = timedelta(minutes=INVESTIGATION_RUNNING_GRACE_MINUTES)

_CALCULATION_INTERVAL_DURATIONS: dict[str, timedelta] = {
    AlertCalculationInterval.REAL_TIME: timedelta(minutes=1),
    AlertCalculationInterval.EVERY_15_MINUTES: timedelta(minutes=15),
    AlertCalculationInterval.HOURLY: timedelta(hours=1),
    AlertCalculationInterval.DAILY: timedelta(days=1),
    AlertCalculationInterval.WEEKLY: timedelta(weeks=1),
    AlertCalculationInterval.MONTHLY: timedelta(days=30),
}


@frozen
class InvestigationDecision:
    should_investigate: bool = False
    # The last verdict an earlier check of this firing episode reached. A check that runs no
    # investigation of its own is held back by it.
    previous_verdict: str | None = None


def investigation_cooldown(alert: AlertConfiguration) -> timedelta:
    """The minimum gap between two investigations of the same alert."""
    interval = _CALCULATION_INTERVAL_DURATIONS.get(alert.calculation_interval or "", MAX_INVESTIGATION_COOLDOWN)
    return min(max(interval - INVESTIGATION_COOLDOWN_MARGIN, MIN_INVESTIGATION_COOLDOWN), MAX_INVESTIGATION_COOLDOWN)


def decide_investigation(alert: AlertConfiguration, alert_check: AlertCheck) -> InvestigationDecision:
    """Whether this firing check gets an investigation, and the episode's last verdict so far.

    Every investigated check of a gated alert holds its notification until its own verdict,
    not only the episode's first fire. Each check of a daily or hourly alert flags a new
    point, so a false positive on a later check is a new false alarm, not a reminder of an
    incident the user already knows about.

    Cooldown is enforced by `claim_investigation_slot`, which does the read-then-write
    inside the caller's transaction.
    """
    if not alert.investigation_agent_enabled:
        return InvestigationDecision()
    if not alert.detector_config:
        return InvestigationDecision()
    if alert_check.state != AlertState.FIRING:
        return InvestigationDecision()

    episode = episode_investigations(alert, alert_check)
    if episode.started >= MAX_INVESTIGATIONS_PER_EPISODE:
        return InvestigationDecision(previous_verdict=episode.previous_verdict)
    return InvestigationDecision(should_investigate=True, previous_verdict=episode.previous_verdict)


def carried_verdict_suppresses(alert: AlertConfiguration, decision: InvestigationDecision) -> bool:
    """Whether a firing check that runs no investigation is held back by the episode's last verdict.

    This covers a check past the episode budget or refused by the cooldown. Without it, the
    budget running out would turn every later false alarm of a long episode into a post.
    """
    return bool(alert.investigation_gates_notifications) and _should_suppress_notification(
        decision.previous_verdict, alert.investigation_inconclusive_action
    )


def claim_investigation_slot(alert: AlertConfiguration, alert_check: AlertCheck) -> bool:
    """Try to claim the investigation slot for `alert` and return True on success.

    Two things fail the claim: an investigation of the same alert that is still in flight
    (PENDING or RUNNING), whatever its age, and one that finished (DONE) inside the
    cooldown window. On success, marks `alert_check.investigation_status = PENDING`; on
    failure, marks it SKIPPED and returns False so flappy alerts don't pile up.

    Caller must run this inside a transaction so the read-then-write is atomic.
    """
    now = datetime.now(UTC)
    in_flight = Q(
        investigation_status__in=[InvestigationStatus.PENDING, InvestigationStatus.RUNNING],
        created_at__gte=now - IN_FLIGHT_INVESTIGATION_HORIZON,
    )
    within_cooldown = Q(
        investigation_status=InvestigationStatus.DONE,
        created_at__gte=now - investigation_cooldown(alert),
    )
    recent = (
        AlertCheck.objects.filter(alert_configuration=alert)
        .exclude(id=alert_check.id)
        .filter(in_flight | within_cooldown)
    )
    if recent.exists():
        AlertCheck.objects.filter(id=alert_check.id).update(investigation_status=InvestigationStatus.SKIPPED)
        return False
    AlertCheck.objects.filter(id=alert_check.id).update(investigation_status=InvestigationStatus.PENDING)
    return True
