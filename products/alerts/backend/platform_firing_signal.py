"""Inbox signals for insight alerts the platform owns that start to fire without the investigation agent.

The insight stack sends these from its own check workflow, and skips every alert the platform owns.
A check marks its firing in `source_detail` (`with_firing_signal`), and the evaluation workflow
emits the signal after the record (`prepare_platform_firing_signals`), through the insight stack's
own gates, cap and payload.
"""

from dataclasses import replace
from datetime import timedelta
from functools import partial
from typing import Final
from uuid import UUID

from django.utils import timezone

import structlog

from posthog.models import Team
from posthog.temporal.alerts.alert_firing_signal import (
    AlertFiringSignal,
    FiringAlert,
    FiringStart,
    prepare_platform_firing_signal,
    signals_every_firing,
)
from posthog.temporal.alerts.investigation import investigates

from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.platform_firing_signal_detail import (
    FIRING_SIGNAL_AFTER_ERRORS_KEY,
    FIRING_SIGNAL_REQUESTED_KEY,
    FiringSignalRequest,
)
from products.alerts.backend.platform_insight_alert import insight_of
from products.alerts_platform.backend.facade import api as platform
from products.alerts_platform.backend.facade.contracts import (
    SOURCE_CONDITION_KEY,
    PlatformAlertCheckInput,
    PlatformAlertConfigurationView,
    SourceBatchEvaluation,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner, PlatformAlertState

logger = structlog.get_logger(__name__)

# How far back a firing that errors looks for the state the errors interrupted.
_INTERRUPTION_LOOKBACK: Final = timedelta(days=30)
_INTERRUPTION_PAGE: Final = 50
# Short, because the emit activity's whole budget covers this wait, the read and the send.
_INTERRUPTION_SLOT_WAIT_SECONDS: Final = 10.0


def with_firing_signal(check: PlatformAlertCheckInput, evaluation: SourceBatchEvaluation) -> SourceBatchEvaluation:
    """The evaluation, with a firing that starts an episode the agent never investigates marked for
    its inbox signal. Only an owned check, because the insight stack signals for the rest.

    Reads no history, so a slow read can never hold back the check. A firing after errors is marked
    as such, and the emit activity decides whether the errors interrupted an earlier firing.
    """
    if not check.owned_by_platform or len(evaluation.outcomes) != 1:
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
    if _investigated(check.team_id, check.legacy_configuration_id):
        return evaluation
    if not signals_every_firing(check.team_id):
        return evaluation
    detail = {**group.source_detail, FIRING_SIGNAL_REQUESTED_KEY: str(check.destination_alert_id)}
    if previous_state == PlatformAlertState.ERRORED.value:
        detail[FIRING_SIGNAL_AFTER_ERRORS_KEY] = True
    group = replace(group, source_detail=detail)
    return replace(evaluation, outcomes=(replace(outcome, groups=(group,)),))


def _investigated(team_id: int, legacy_configuration_id: UUID | None) -> bool:
    """Whether the investigation agent decides this alert's firings. It runs only for an alert that
    still has an insight stack row, so an alert with none is never investigated."""
    if legacy_configuration_id is None:
        return False
    alert = (
        AlertConfiguration.objects.filter(team_id=team_id, id=legacy_configuration_id)
        .only("id", "investigation_agent_enabled", "detector_config")
        .first()
    )
    return alert is not None and investigates(alert, firing=True)


def _resumes_after_errors(request: FiringSignalRequest) -> bool:
    return request.after_errors and _resumes_interrupted_firing(request)


def _resumes_interrupted_firing(request: FiringSignalRequest) -> bool:
    """Whether the errors before this check interrupted a firing, as the insight stack decides it.

    An insight alert's failed check ends its platform firing, so without this a transient query
    error during an incident would file a second signal. An unreadable history counts as resumed,
    because a missed signal costs less than a duplicate report. So is a history with no move into
    the errors, because those errors began before the window it reads.
    """
    # Imported here, because the check cycle imports this module.
    from products.alerts.backend.platform_source_cycle import ClickHouseQuerySlot  # noqa: PLC0415

    holder = f"firing-signal:{request.configuration_id}:{request.episode_started_at.isoformat()}"
    try:
        with ClickHouseQuerySlot(holder, wait_seconds=_INTERRUPTION_SLOT_WAIT_SECONDS)():
            page = platform.notable_checks_by_public_id(
                team_id=request.team_id,
                public_id=UUID(request.alert_id),
                since=timezone.now() - _INTERRUPTION_LOOKBACK,
                limit=_INTERRUPTION_PAGE,
            )
    except Exception:
        logger.exception("Failed to read a platform insight alert's history", alert_id=request.alert_id)
        return True
    if page is None:
        return True
    for event in page.events:
        if event.state == PlatformAlertState.ERRORED and event.previous_state != PlatformAlertState.ERRORED:
            return event.previous_state == PlatformAlertState.FIRING
    return True


def prepare_platform_firing_signals(requests: tuple[FiringSignalRequest, ...]) -> list[AlertFiringSignal]:
    """The signals the recorded firings asked for, through the insight stack's gates and cap.

    Reads the platform's configuration and its insight, not the insight stack's row, so an alert
    with no row signals too. Runs the gates against the alert as it is now, so an edit since the
    check can still stop a signal. Skips an alert that was deleted, disabled or handed back since.
    Never raises.
    """
    signals = []
    for request in requests:
        try:
            found = _firing_alert(request)
            if found is None:
                continue
            alert, legacy_configuration_id = found
            firing = FiringStart(
                # The platform's id for the episode, so a retried emission keeps the same source id.
                check_id=f"{request.configuration_id}:{request.episode_started_at.isoformat()}",
                started_at=request.episode_started_at,
                triggered_dates=request.triggered_dates,
            )
            signal = prepare_platform_firing_signal(
                alert,
                firing,
                breaches=list(request.breaches),
                investigated=_investigated(request.team_id, legacy_configuration_id),
                resumes_interrupted_episode=partial(_resumes_after_errors, request),
            )
        except Exception:
            logger.exception("Failed to prepare a platform insight firing's signal", alert_id=request.alert_id)
            continue
        if signal is not None:
            signals.append(signal)
    return signals


def _firing_alert(request: FiringSignalRequest) -> tuple[FiringAlert, UUID | None] | None:
    """The alert as the gates read it, and its insight stack row's id, or None when it no longer signals."""
    configuration = platform.get_configuration(
        team_id=request.team_id,
        source_kinds=[SourceKind.INSIGHT.value],
        configuration_id=UUID(request.configuration_id),
    )
    if configuration is None or not configuration.enabled or configuration.owner != PlatformAlertOwner.PLATFORM.value:
        return None
    if not _records_firing(configuration, request):
        return None
    insight = insight_of(request.team_id, configuration.source_config)
    if insight is None:
        return None
    condition = configuration.source_config.get(SOURCE_CONDITION_KEY) or {}
    alert = FiringAlert(
        team=Team.objects.select_related("organization").get(id=request.team_id),
        id=str(configuration.destination_alert_id),
        name=configuration.name,
        insight=insight,
        detector_config=condition.get("detector"),
    )
    return alert, configuration.legacy_configuration_id


def _records_firing(configuration: PlatformAlertConfigurationView, request: FiringSignalRequest) -> bool:
    """Whether the alert holds the firing the request names, unmuted. A record skips a check whose
    alert was snoozed or edited while it ran, and its request must then file nothing."""
    now = timezone.now()
    if configuration.snooze_until is not None and configuration.snooze_until > now:
        return False
    return any(
        instance.state == PlatformAlertState.FIRING.value
        and instance.firing_started_at == request.episode_started_at
        and (instance.snooze_until is None or instance.snooze_until <= now)
        for instance in configuration.alerts
    )
