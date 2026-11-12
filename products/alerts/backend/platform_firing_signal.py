"""Inbox signals for insight alerts the platform owns that start to fire without the investigation agent.

The insight stack sends these from its own check workflow, and skips every alert the platform owns.
A check marks its firing in `source_detail` (`with_firing_signal`), and the evaluation workflow
emits the signal after the record (`prepare_platform_firing_signals`), through the insight stack's
own gates, cap and payload.
"""

import hashlib
from dataclasses import replace
from datetime import timedelta
from functools import partial
from typing import Final
from uuid import UUID

from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
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
from products.alerts.backend.platform_insight_alert import (
    alert_from_platform,
    evaluation_alert,
    insight_of,
    legacy_alert,
)
from products.alerts_platform.backend.facade import api as platform
from products.alerts_platform.backend.facade.contracts import (
    SOURCE_CONDITION_KEY,
    GroupOutcome,
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
    """The evaluation, with each firing that starts an episode the agent never investigates marked for
    its inbox signal. A breakdown alert marks every value whose firing starts its own episode. Only an
    owned check, because the insight stack signals for the rest.

    Reads no history, so a slow read can never hold back the check. An ungrouped firing after errors
    is marked as such, and the emit activity decides whether the errors interrupted an earlier firing.
    """
    if not check.owned_by_platform or len(evaluation.outcomes) != 1:
        return evaluation
    outcome = evaluation.outcomes[0]
    if outcome.skipped:
        return evaluation
    starting = {
        group.grouping_key
        for group in outcome.groups
        if _starts_episode(check, group) and not _resumes_interrupted_value(check, group)
    }
    if not starting:
        return evaluation
    if len(outcome.groups) == 1 and _agent_investigates(evaluation_alert(check)):
        return evaluation
    if not signals_every_firing(check.team_id):
        return evaluation
    groups = tuple(
        _requesting_signal(check, group) if group.grouping_key in starting else group for group in outcome.groups
    )
    return replace(evaluation, outcomes=(replace(outcome, groups=groups),))


def _starts_episode(check: PlatformAlertCheckInput, group: GroupOutcome) -> bool:
    episode = group.firing_episode
    if group.new_state != PlatformAlertState.FIRING.value or episode is None or episode.ended:
        return False
    # The insight stack runs no check while an alert is snoozed, so a muted firing files nothing.
    return not group.muted_notification and check.instance(group.grouping_key).state != PlatformAlertState.FIRING.value


def _resumes_interrupted_value(check: PlatformAlertCheckInput, group: GroupOutcome) -> bool:
    """Whether errors interrupted this breakdown value's firing. The history the emit activity reads
    holds only the ungrouped instance, so a value decides from its own, which keeps its firing's
    start through a failed check."""
    instance = check.instance(group.grouping_key)
    return (
        bool(group.grouping_key)
        and instance.state == PlatformAlertState.ERRORED.value
        and instance.firing_started_at is not None
    )


def _requesting_signal(check: PlatformAlertCheckInput, group: GroupOutcome) -> GroupOutcome:
    detail = {**group.source_detail, FIRING_SIGNAL_REQUESTED_KEY: str(check.destination_alert_id)}
    if not group.grouping_key and check.instance().state == PlatformAlertState.ERRORED.value:
        detail[FIRING_SIGNAL_AFTER_ERRORS_KEY] = True
    return replace(group, source_detail=detail)


def _agent_investigates(alert: AlertConfiguration | None) -> bool:
    """Whether the investigation agent decides this alert's firings, and files their signal after its
    verdict. The alert is the one the check evaluates: its insight stack row, or one built from the
    platform alert. The agent takes only a check with one group (`with_investigation`)."""
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
    Reads each configuration once, however many of its breakdown values started firing. Never raises.
    """
    signals = []
    configured: dict[tuple[int, str], _ConfiguredAlert | None] = {}
    for request in requests:
        try:
            key = (request.team_id, request.configuration_id)
            if key not in configured:
                # Set before the read, so a configuration that fails to read is not read again.
                configured[key] = None
                configured[key] = _configured_alert(request.team_id, request.configuration_id)
            found = configured[key]
            if found is None or not _records_firing(found.configuration, request):
                continue
            firing = FiringStart(
                check_id=_episode_id(request),
                started_at=request.episode_started_at,
                triggered_dates=request.triggered_dates,
            )
            signal = prepare_platform_firing_signal(
                found.alert,
                firing,
                breaches=list(request.breaches),
                investigated=request.investigable
                and _agent_investigates(_evaluated_alert(request.team_id, found.configuration)),
                resumes_interrupted_episode=partial(_resumes_after_errors, request),
            )
        except Exception:
            logger.exception("Failed to prepare a platform insight firing's signal", alert_id=request.alert_id)
            continue
        if signal is not None:
            signals.append(signal)
    return signals


def _episode_id(request: FiringSignalRequest) -> str:
    """The platform's id for the episode, so a retried emission keeps the same source id. A breakdown
    value's adds a digest of its key, so each value's episode gets its own id at a bounded length."""
    episode = request.episode_started_at.isoformat()
    if not request.grouping_key:
        return f"{request.configuration_id}:{episode}"
    digest = hashlib.sha256(request.grouping_key.encode("utf-8", "surrogatepass")).hexdigest()[:16]
    return f"{request.configuration_id}:{digest}:{episode}"


def _evaluated_alert(team_id: int, configuration: PlatformAlertConfigurationView) -> AlertConfiguration | None:
    """The alert a check of `configuration` evaluates, as `evaluation_alert` reads it for a check."""
    if configuration.legacy_configuration_id is None:
        return alert_from_platform(configuration, team_id=team_id, enabled=configuration.enabled)
    return legacy_alert(team_id=team_id, alert_id=configuration.legacy_configuration_id)


@frozen
class _ConfiguredAlert:
    alert: FiringAlert
    configuration: PlatformAlertConfigurationView


def _configured_alert(team_id: int, configuration_id: str) -> _ConfiguredAlert | None:
    """The alert as the gates read it, and its configuration, or None when it no longer signals."""
    configuration = platform.get_configuration(
        team_id=team_id,
        source_kinds=[SourceKind.INSIGHT.value],
        configuration_id=UUID(configuration_id),
    )
    if configuration is None or not configuration.enabled or configuration.owner != PlatformAlertOwner.PLATFORM.value:
        return None
    insight = insight_of(team_id, configuration.source_config)
    if insight is None:
        return None
    condition = configuration.source_config.get(SOURCE_CONDITION_KEY) or {}
    alert = FiringAlert(
        team=Team.objects.select_related("organization").get(id=team_id),
        id=str(configuration.destination_alert_id),
        name=configuration.name,
        insight=insight,
        detector_config=condition.get("detector"),
    )
    return _ConfiguredAlert(alert=alert, configuration=configuration)


def _records_firing(configuration: PlatformAlertConfigurationView, request: FiringSignalRequest) -> bool:
    """Whether the alert's instance for the request's group holds the firing it names, unmuted. A record
    skips a check whose alert was snoozed or edited while it ran, and its request must then file nothing."""
    now = timezone.now()
    if configuration.snooze_until is not None and configuration.snooze_until > now:
        return False
    return any(
        instance.grouping_key == request.grouping_key
        and instance.state == PlatformAlertState.FIRING.value
        and instance.firing_started_at == request.episode_started_at
        and (instance.snooze_until is None or instance.snooze_until <= now)
        for instance in configuration.alerts
    )
