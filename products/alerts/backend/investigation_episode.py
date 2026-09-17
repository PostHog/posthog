"""Reads the firing episode an AlertCheck belongs to.

An episode is the run of consecutive FIRING checks since the last check that was not
FIRING. The investigation agent budgets its work per episode, and it groups everything
it publishes about one incident under the episode's first check.
"""

from __future__ import annotations

from posthog.schema import AlertState

from posthog.dataclasses import frozen

from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration, InvestigationStatus

# Statuses of a check whose investigation was started. SKIPPED never ran, so it costs no
# budget; FAILED did run and costs one, which keeps a broken agent from retrying forever.
_STARTED_INVESTIGATION_STATUSES = [
    InvestigationStatus.PENDING,
    InvestigationStatus.RUNNING,
    InvestigationStatus.DONE,
    InvestigationStatus.FAILED,
]


@frozen
class EpisodeInvestigations:
    """What the current firing episode already spent, seen from one check in it."""

    started: int
    first_check_id: str
    previous_verdict: str | None
    # True when no earlier check of this episode fired, so this is the fire the user has not
    # been told about yet. The count of started investigations cannot answer that: a check
    # whose investigation the cooldown refused still sent its notification.
    is_first_fire: bool


def episode_investigations(alert: AlertConfiguration, alert_check: AlertCheck) -> EpisodeInvestigations:
    """Read the firing episode that `alert_check` belongs to.

    The episode starts after the most recent check that was not FIRING, so a check that
    does not fire resets the budget for the next episode.
    """
    earlier = AlertCheck.objects.filter(
        alert_configuration=alert,
        created_at__lte=alert_check.created_at,
    ).exclude(id=alert_check.id)

    episode_start = (
        earlier.exclude(state=AlertState.FIRING).order_by("-created_at").values_list("created_at", flat=True).first()
    )
    if episode_start is not None:
        earlier = earlier.filter(created_at__gt=episode_start)

    first_check_id = earlier.order_by("created_at").values_list("id", flat=True).first()
    previous_verdict = (
        earlier.filter(investigation_verdict__isnull=False)
        .order_by("-created_at")
        .values_list("investigation_verdict", flat=True)
        .first()
    )
    return EpisodeInvestigations(
        started=earlier.filter(investigation_status__in=_STARTED_INVESTIGATION_STATUSES).count(),
        first_check_id=str(first_check_id or alert_check.id),
        previous_verdict=previous_verdict,
        is_first_fire=first_check_id is None,
    )
