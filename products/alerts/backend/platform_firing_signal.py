"""The Inbox signal for an insight alert the platform owns, when a check starts a firing episode.

The same gates as the insight stack's own (`posthog/temporal/alerts/alert_firing_signal.py`), read
from the platform's configuration and its insight rather than from `AlertConfiguration` and
`AlertCheck`, so an alert with no insight stack row signals too.
"""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import structlog

from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.alerts.alert_firing_signal import (
    AlertFiringEpisode,
    AlertFiringSignal,
    dispatch_alert_firing_signal,
    prepare_episode_firing_signal,
)
from posthog.temporal.alerts.investigation import investigates

from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.platform_firing_signal_detail import FIRING_SIGNAL_REQUESTED_KEY, FiringSignalRequest
from products.alerts_platform.backend.facade.api import get_configuration
from products.alerts_platform.backend.facade.contracts import (
    SOURCE_CONDITION_KEY,
    PlatformAlertCheckInput,
    SourceBatchEvaluation,
    SourceKind,
)
from products.alerts_platform.backend.facade.lifecycle import FIRING_STATES, AlertState
from products.product_analytics.backend.facade.models import Insight

logger = structlog.get_logger(__name__)


def with_firing_signal(check: PlatformAlertCheckInput, evaluation: SourceBatchEvaluation) -> SourceBatchEvaluation:
    """The evaluation of a check the platform owns, with the firing that starts the alert's episode
    marked for a signal. A source-owned check gets its signal from the insight stack."""
    if not check.owned_by_platform or len(evaluation.outcomes) != 1:
        return evaluation
    outcome = evaluation.outcomes[0]
    if outcome.skipped or _was_firing(check):
        return evaluation
    groups = list(outcome.groups)
    index = next((i for i, group in enumerate(groups) if group.new_state == AlertState.FIRING.value), None)
    if index is None:
        return evaluation
    groups[index] = replace(
        groups[index], source_detail={**groups[index].source_detail, FIRING_SIGNAL_REQUESTED_KEY: True}
    )
    return replace(evaluation, outcomes=(replace(outcome, groups=tuple(groups)),))


def _was_firing(check: PlatformAlertCheckInput) -> bool:
    """Whether the alert was inside a firing episode before this check, as a whole rather than per group.

    A failed check reads as ERRORED but leaves each instance's firing in place underneath, so an
    alert that fails during an incident and fires again resumes that episode, as the insight stack
    skips its errored checks to find the last real state.
    """
    return any(
        instance.state in FIRING_STATES
        or (instance.state == AlertState.ERRORED.value and instance.firing_started_at is not None)
        for instance in check.instances
    )


def prepare_platform_firing_signal(request: FiringSignalRequest) -> AlertFiringSignal | None:
    """Run the gates and build the signal, or return None to skip it. Never raises. Call it from a thread."""
    try:
        episode = _episode(request)
    except Exception:
        logger.exception("alert_firing.platform_signal_read_failed", configuration_id=request.configuration_id)
        return None
    if episode is None:
        return None
    return prepare_episode_firing_signal(episode, breaches=list(request.breaches))


def _episode(request: FiringSignalRequest) -> AlertFiringEpisode | None:
    configuration = get_configuration(
        team_id=request.team_id,
        source_kinds=[SourceKind.INSIGHT.value],
        configuration_id=UUID(request.configuration_id),
    )
    # As the insight stack: switching an alert off or deleting it since the check stops the signal.
    if configuration is None or not configuration.enabled:
        return None
    insight_id = configuration.source_config.get("insight_id")
    if insight_id is None:
        return None
    insight = (
        Insight.objects.filter(team_id=request.team_id, id=insight_id, deleted=False)
        .only("id", "name", "derived_name", "short_id")
        .first()
    )
    if insight is None:
        return None
    # The agent investigates only a firing of an alert the insight stack also keeps, so one without a row is never investigated.
    legacy = (
        AlertConfiguration.objects.filter(team_id=request.team_id, id=configuration.legacy_configuration_id)
        .only("id", "investigation_agent_enabled", "detector_config")
        .first()
        if configuration.legacy_configuration_id is not None
        else None
    )
    condition = configuration.source_config.get(SOURCE_CONDITION_KEY) or {}
    started_at = request.episode_started_at
    return AlertFiringEpisode(
        team=Team.objects.select_related("organization").get(id=request.team_id),
        alert_id=str(configuration.destination_alert_id),
        # The platform has no check row, so the evaluation names the check that started the episode.
        alert_check_id=f"{configuration.id}:{request.evaluation_key}",
        alert_name=configuration.name,
        insight=insight,
        detector_config=condition.get("detector"),
        investigated=legacy is not None and investigates(legacy, firing=True),
        episode_started_at=datetime.fromisoformat(started_at) if started_at else datetime.now(UTC),
        triggered_dates=list(request.triggered_dates) or None,
    )


async def emit_platform_firing_signals(requests: tuple[FiringSignalRequest, ...]) -> int:
    """Sends each request's signal that passes the gates. Returns how many it sent. Never raises."""
    prepare = database_sync_to_async(prepare_platform_firing_signal, thread_sensitive=False)
    signals = [signal for signal in await asyncio.gather(*(prepare(request) for request in requests)) if signal]
    # On the event loop, not in the thread: `emit_signal` needs the default executor.
    dispatched = await asyncio.gather(*(dispatch_alert_firing_signal(signal) for signal in signals))
    return sum(dispatched)
