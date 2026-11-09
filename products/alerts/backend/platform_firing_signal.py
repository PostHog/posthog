"""Inbox signals for insight alerts the platform owns that start to fire without the investigation agent.

The insight stack sends these from its own check workflow, and skips every alert the platform owns.
A check marks its firing in `source_detail` (`with_firing_signal`), and the evaluation workflow
emits the signal after the record (`prepare_platform_firing_signals`), through the insight stack's
own gates, cap and payload.
"""

from dataclasses import replace
from datetime import timedelta
from typing import Final
from uuid import UUID

from django.utils import timezone

import structlog

from posthog.temporal.alerts.alert_firing_signal import AlertFiringSignal, FiringStart, prepare_platform_firing_signal
from posthog.temporal.alerts.investigation import investigates

from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.platform_firing_signal_detail import FIRING_SIGNAL_REQUESTED_KEY, FiringSignalRequest
from products.alerts_platform.backend.facade import api as platform
from products.alerts_platform.backend.facade.contracts import PlatformAlertCheckInput, SourceBatchEvaluation
from products.alerts_platform.backend.facade.enums import PlatformAlertState
from products.signals.backend.facade.source_configs import AlertScope, get_analytics_alert_scope

logger = structlog.get_logger(__name__)

# How far back a firing that errors looks for the state the errors interrupted.
_INTERRUPTION_LOOKBACK: Final = timedelta(days=30)
_INTERRUPTION_PAGE: Final = 50


def with_firing_signal(check: PlatformAlertCheckInput, evaluation: SourceBatchEvaluation) -> SourceBatchEvaluation:
    """The evaluation, with a firing that starts an episode the agent never investigates marked for
    its inbox signal. Only an owned check, because the insight stack signals for the rest."""
    if not check.owned_by_platform or check.legacy_configuration_id is None or len(evaluation.outcomes) != 1:
        return evaluation
    outcome = evaluation.outcomes[0]
    if outcome.skipped or len(outcome.groups) != 1:
        return evaluation
    group = outcome.groups[0]
    episode = group.firing_episode
    if group.new_state != PlatformAlertState.FIRING.value or episode is None or episode.ended:
        return evaluation
    if group.muted_notification:
        # The insight stack runs no check while an alert is snoozed, so a muted firing files nothing.
        return evaluation
    previous_state = check.instance().state
    if previous_state == PlatformAlertState.FIRING.value:
        return evaluation
    alert = (
        AlertConfiguration.objects.select_related("insight")
        .filter(team_id=check.team_id, id=check.legacy_configuration_id)
        .first()
    )
    if alert is None or investigates(alert, firing=True):
        return evaluation
    # Before the history read, because few teams turn every firing into a signal.
    if get_analytics_alert_scope(team_id=check.team_id) != AlertScope.ALL_FIRING_ALERTS:
        return evaluation
    if previous_state == PlatformAlertState.ERRORED.value and _resumes_interrupted_firing(
        check.team_id, check.legacy_configuration_id
    ):
        return evaluation
    group = replace(group, source_detail={**group.source_detail, FIRING_SIGNAL_REQUESTED_KEY: str(alert.id)})
    return replace(evaluation, outcomes=(replace(outcome, groups=(group,)),))


def _resumes_interrupted_firing(team_id: int, public_id: UUID) -> bool:
    """Whether the errors before this check interrupted a firing, as the insight stack decides it.

    An insight alert's failed check ends its platform firing, so without this a transient query
    error during an incident would file a second signal. An unreadable history counts as resumed,
    because a missed signal costs less than a duplicate report.
    """
    try:
        page = platform.notable_checks_by_public_id(
            team_id=team_id,
            public_id=public_id,
            since=timezone.now() - _INTERRUPTION_LOOKBACK,
            limit=_INTERRUPTION_PAGE,
        )
    except Exception:
        logger.exception("Failed to read a platform insight alert's history", alert_id=str(public_id))
        return True
    if page is None:
        return True
    for event in page.events:
        if event.state == PlatformAlertState.ERRORED and event.previous_state != PlatformAlertState.ERRORED:
            return event.previous_state == PlatformAlertState.FIRING
    # No move into ERRORED in the page: the history is too long or missing, so it cannot be ruled out.
    return page.total > len(page.events)


def prepare_platform_firing_signals(requests: tuple[FiringSignalRequest, ...]) -> list[AlertFiringSignal]:
    """The signals the recorded firings asked for, through the insight stack's gates and cap.

    Runs the gates against the alert as it is now, so an edit since the check can still stop a
    signal. Skips an alert that was deleted, disabled or handed back since. Never raises.
    """
    signals = []
    for request in requests:
        try:
            alert = (
                AlertConfiguration.objects.select_related("insight", "team__organization")
                .filter(team_id=request.team_id, id=request.alert_id)
                .first()
            )
            if alert is None or not alert.enabled or not alert.platform_owned:
                continue
            firing = FiringStart(
                # The platform's id for the episode, so a retried emission keeps the same source id.
                check_id=f"{request.configuration_id}:{request.episode_started_at.isoformat()}",
                started_at=request.episode_started_at,
                triggered_dates=request.triggered_dates,
            )
            signal = prepare_platform_firing_signal(alert, firing, breaches=list(request.breaches))
        except Exception:
            logger.exception("Failed to prepare a platform insight firing's signal", alert_id=request.alert_id)
            continue
        if signal is not None:
            signals.append(signal)
    return signals
