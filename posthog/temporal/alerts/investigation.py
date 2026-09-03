"""Investigation-agent trigger helpers used by the Temporal evaluate_alert activity.

The trigger and notification-gating decisions both run inside `evaluate_alert`
in the same DB transaction as the AlertCheck insert, so the read-then-write that
claims the cooldown lease stays consistent. This module exposes the primitives
as pure functions so they can be unit-tested independently of Temporal.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from posthog.schema import AlertCalculationInterval, AlertState

from posthog.dataclasses import frozen

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
    is_first_of_episode: bool = False


def investigation_cooldown(alert: AlertConfiguration) -> timedelta:
    """The minimum gap between two investigations of the same alert."""
    interval = _CALCULATION_INTERVAL_DURATIONS.get(alert.calculation_interval, MAX_INVESTIGATION_COOLDOWN)
    return min(max(interval - INVESTIGATION_COOLDOWN_MARGIN, MIN_INVESTIGATION_COOLDOWN), MAX_INVESTIGATION_COOLDOWN)


def decide_investigation(alert: AlertConfiguration, alert_check: AlertCheck) -> InvestigationDecision:
    """Whether this firing check gets an investigation, and whether it is the episode's first.

    Only the first investigation of an episode may gate the notification. A later one
    runs while the notification goes out on the normal path, because holding every
    reminder of a long incident costs the user more than the verdict is worth.

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
        return InvestigationDecision()
    return InvestigationDecision(should_investigate=True, is_first_of_episode=episode.is_first)


def claim_investigation_slot(alert: AlertConfiguration, alert_check: AlertCheck) -> bool:
    """Try to claim the cooldown slot for `alert` and return True on success.

    On success, marks `alert_check.investigation_status = PENDING`. On failure
    (a recent investigation is RUNNING/DONE/PENDING within the cooldown window),
    marks it SKIPPED and returns False so flappy alerts don't pile up.

    Caller must run this inside a transaction so the read-then-write is atomic.
    """
    cooldown_since = datetime.now(UTC) - investigation_cooldown(alert)
    recent = AlertCheck.objects.filter(
        alert_configuration=alert,
        created_at__gte=cooldown_since,
        investigation_status__in=[
            InvestigationStatus.RUNNING,
            InvestigationStatus.DONE,
            InvestigationStatus.PENDING,
        ],
    ).exclude(id=alert_check.id)
    if recent.exists():
        AlertCheck.objects.filter(id=alert_check.id).update(investigation_status=InvestigationStatus.SKIPPED)
        return False
    AlertCheck.objects.filter(id=alert_check.id).update(investigation_status=InvestigationStatus.PENDING)
    return True
