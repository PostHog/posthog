"""Inbox signals for insight alerts that start to fire without the investigation agent.

The investigation agent emits its own `analytics` / `anomaly_investigation` signal after the verdict.
This path covers the alerts it never investigates, for teams whose product analytics source has the
`all_firing_alerts` scope. It emits one signal per firing episode, from the check that starts it.
"""

from __future__ import annotations

import enum
import asyncio
from collections.abc import Callable
from datetime import datetime

import structlog
import posthoganalytics
from redis.exceptions import RedisError

from posthog.schema import AlertState

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.models import Team
from posthog.redis import get_client
from posthog.temporal.alerts.investigation import investigates
from posthog.temporal.alerts.metrics import record_alert_firing_signal_outcome
from posthog.token_bucket import BucketUnavailable, Budget, consume, refund
from posthog.utils import absolute_uri

from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration
from products.product_analytics.backend.facade.models import Insight
from products.signals.backend.facade.api import emit_signal
from products.signals.backend.facade.signal_extras import AnalyticsAlertFiringSignalExtra
from products.signals.backend.facade.source_configs import (
    AlertFilterOutcome,
    evaluate_alert_filter,
    get_analytics_alert_name_patterns,
    get_analytics_alert_scope,
    get_source_config,
)

logger = structlog.get_logger(__name__)

SIGNAL_SOURCE_PRODUCT = "analytics"
SIGNAL_SOURCE_TYPE = "alert_firing"
# The product analytics source row. Its `enabled` flag and its alert config keys govern this signal too.
_SOURCE_CONFIG_TYPE = "anomaly_investigation"
_ALL_FIRING_ALERTS = "all_firing_alerts"

# Rollout cap per team: a burst of 20 episodes, then about one per hour. Each signal costs a pipeline
# run, and a team with many noisy alerts must not flood its inbox or our spend.
CAP_BUDGET = Budget(burst=20, per_hour=1)

# `emit_signal` has no time limit of its own, and its guidance check can take about 20 seconds.
EMISSION_TIMEOUT_SECONDS = 30

# Same margin under the facade's description token limit as the investigation signal.
_MAX_DESCRIPTION_CHARS = 3000
_MAX_BREACHES = 20


class AlertFiringSkipReason(enum.StrEnum):
    NOT_NEW_EPISODE = "not_new_episode"
    INVESTIGATED = "investigated"
    SOURCE_DISABLED = "source_disabled"
    SCOPE = "scope"
    FILTERED = "filtered"
    # Logged apart from FILTERED, so a broken filter that drops every alert is not read as a quiet one.
    FILTER_INVALID = "filter_invalid"
    CAP = "cap"
    CAP_UNAVAILABLE = "cap_unavailable"
    NOT_DISPATCHED = "not_dispatched"


# Nearly every check fails one of these, so a log line or an outcome count for them would only be noise.
_UNLOGGED_SKIP_REASONS = frozenset({AlertFiringSkipReason.NOT_NEW_EPISODE, AlertFiringSkipReason.INVESTIGATED})

EMITTED_OUTCOME = "emitted"
CAP_DROP_EVENT = "alert firing signal skipped"
_CAP_DROP_REASONS = frozenset({AlertFiringSkipReason.CAP, AlertFiringSkipReason.CAP_UNAVAILABLE})
# Longer than every attempt of the emit activity together, so a retry finds the outcome of the first attempt.
_OUTCOME_KEY_TTL_SECONDS = 60 * 60


def cap_key(team_id: int) -> str:
    return f"signals_alert_firing_rate:{team_id}"


def _outcome_key(source_id: str) -> str:
    return f"signals_alert_firing_outcome:{source_id}"


def _source_id(alert_id: str, alert_check_id: str) -> str:
    return f"{alert_id}:{alert_check_id}"


def alert_firing_skip_reason(
    alert: AlertConfiguration, *, previous_state: str, new_state: str
) -> AlertFiringSkipReason | None:
    """The in-memory gates. They run before any read, because most checks fail them."""
    if new_state != AlertState.FIRING or previous_state == AlertState.FIRING:
        return AlertFiringSkipReason.NOT_NEW_EPISODE
    if investigates(alert, firing=True):
        # The agent's verdict decides for these alerts, in both scopes.
        return AlertFiringSkipReason.INVESTIGATED
    return None


@frozen
class AlertFiringEpisode:
    """The firing episode a signal describes, read from whichever stack evaluated the alert."""

    team: Team
    alert_id: str
    # The check that started the episode. With `alert_id`, it is the signal's source id.
    alert_check_id: str
    alert_name: str | None
    insight: Insight
    detector_config: dict | None
    # The agent investigates this alert's firings, and its verdict decides the signal instead.
    investigated: bool
    episode_started_at: datetime
    triggered_dates: list | None = None


@frozen
class AlertFiringSignal:
    """A signal that passed every gate and charged the cap, ready to dispatch."""

    team: Team
    alert_id: str
    alert_check_id: str
    description: str
    extra: dict


def prepare_alert_firing_signal(
    alert: AlertConfiguration, alert_check: AlertCheck, *, previous_state: str, breaches: list[str] | None
) -> AlertFiringSignal | None:
    """Run the gates and build the signal, or return None to skip it. Never raises.

    Call it from a thread, after the check is committed and outside the alert row lock.
    It charges the cap, and `dispatch_alert_firing_signal` refunds the charge when nothing is sent.
    """

    def prepare() -> tuple[AlertFiringSkipReason | None, AlertFiringSignal | None]:
        skip_reason = alert_firing_skip_reason(alert, previous_state=previous_state, new_state=alert_check.state)
        if skip_reason is not None:
            return skip_reason, None
        return _prepare(
            _legacy_episode(alert, alert_check),
            breaches or [],
            resumes_interrupted_episode=lambda: (
                previous_state == AlertState.ERRORED and _resumes_interrupted_episode(alert, alert_check)
            ),
        )

    return _prepared(alert.team_id, str(alert.id), str(alert_check.id), lambda: alert.team, prepare)


def prepare_episode_firing_signal(
    load_episode: Callable[[], AlertFiringEpisode | None],
    *,
    team_id: int,
    alert_id: str,
    alert_check_id: str,
    breaches: list[str],
) -> AlertFiringSignal | None:
    """`prepare_alert_firing_signal` for a check that its caller already knows started a firing episode,
    such as one the alerts platform evaluated. `load_episode` returns None for an alert that is gone.
    """

    def prepare() -> tuple[AlertFiringSkipReason | None, AlertFiringSignal | None]:
        episode = load_episode()
        if episode is None:
            return None, None
        if episode.investigated:
            return AlertFiringSkipReason.INVESTIGATED, None
        return _prepare(episode, breaches, resumes_interrupted_episode=lambda: False)

    return _prepared(team_id, alert_id, alert_check_id, lambda: Team.objects.get(id=team_id), prepare)


def _prepared(
    team_id: int,
    alert_id: str,
    alert_check_id: str,
    team: Callable[[], Team],
    prepare: Callable[[], tuple[AlertFiringSkipReason | None, AlertFiringSignal | None]],
) -> AlertFiringSignal | None:
    try:
        skip_reason, signal = prepare()
    except Exception:
        logger.exception("alert_firing.signal_prepare_failed", alert_id=alert_id, alert_check_id=alert_check_id)
        return None
    if skip_reason is not None and skip_reason not in _UNLOGGED_SKIP_REASONS:
        _log_skip(team_id, alert_id, alert_check_id, skip_reason)
        _record_outcome(team(), alert_id, alert_check_id, skip_reason)
    return signal


async def dispatch_alert_firing_signal(signal: AlertFiringSignal) -> bool:
    """Send a prepared signal. Returns whether it was dispatched. Never raises.

    Await it from the activity's event loop, not from a thread. `emit_signal` runs sync work on the
    default executor, so a call that blocks an executor thread on it can deadlock once every executor
    thread waits the same way. A failure never changes the committed check.
    """
    source_id = _source_id(signal.alert_id, signal.alert_check_id)
    try:
        async with asyncio.timeout(EMISSION_TIMEOUT_SECONDS):
            dispatched = await emit_signal(
                team=signal.team,
                source_product=SIGNAL_SOURCE_PRODUCT,
                source_type=SIGNAL_SOURCE_TYPE,
                source_id=source_id,
                # Same key on a retried attempt, so one episode starts at most one emission.
                idempotency_key=source_id,
                description=signal.description,
                weight=1,
                extra=signal.extra,
            )
    except asyncio.CancelledError:
        # A cancelled attempt sends nothing, so it gives back its token. The shield lets the refund
        # finish if a second cancel arrives while it runs.
        await asyncio.shield(asyncio.to_thread(refund, cap_key(signal.team.id), CAP_BUDGET))
        raise
    except Exception:
        logger.exception(
            "alert_firing.signal_emission_failed", alert_id=signal.alert_id, alert_check_id=signal.alert_check_id
        )
        dispatched = None
    if dispatched:
        logger.info("alert_firing.signal_emitted", alert_id=signal.alert_id, alert_check_id=signal.alert_check_id)
        await asyncio.to_thread(_record_outcome, signal.team, signal.alert_id, signal.alert_check_id, None)
        return True
    await asyncio.to_thread(refund, cap_key(signal.team.id), CAP_BUDGET)
    if dispatched is False:
        reason = AlertFiringSkipReason.NOT_DISPATCHED
        _log_skip(signal.team.id, signal.alert_id, signal.alert_check_id, reason)
        await asyncio.to_thread(_record_outcome, signal.team, signal.alert_id, signal.alert_check_id, reason)
    return False


def _log_skip(team_id: int, alert_id: str, alert_check_id: str, reason: AlertFiringSkipReason) -> None:
    logger.info(
        "alert_firing.signal_skipped",
        team_id=team_id,
        alert_id=alert_id,
        alert_check_id=alert_check_id,
        reason=reason.value,
    )


def _record_outcome(team: Team, alert_id: str, alert_check_id: str, skip_reason: AlertFiringSkipReason | None) -> None:
    """Count the outcome of an episode once, and capture a cap drop for the team. Never raises.

    Call it from a thread. A cancelled attempt records nothing, because its retry decides again.
    """
    source_id = _source_id(alert_id, alert_check_id)
    try:
        if not _claims_outcome(source_id):
            return
        record_alert_firing_signal_outcome(EMITTED_OUTCOME if skip_reason is None else skip_reason.value)
        if skip_reason is not None and skip_reason in _CAP_DROP_REASONS:
            posthoganalytics.capture(
                event=CAP_DROP_EVENT,
                distinct_id=str(team.uuid),
                properties={
                    "source_product": SIGNAL_SOURCE_PRODUCT,
                    "source_type": SIGNAL_SOURCE_TYPE,
                    "source_id": source_id,
                    "team_id": team.id,
                    "alert_id": alert_id,
                    "alert_check_id": alert_check_id,
                    "reason": skip_reason.value,
                },
                groups=groups(team.organization, team),
            )
    except Exception:
        logger.exception(
            "alert_firing.signal_outcome_failed", team_id=team.id, alert_id=alert_id, alert_check_id=alert_check_id
        )


def _claims_outcome(source_id: str) -> bool:
    """Whether this attempt is the first to record an outcome for the episode.

    It uses the emission idempotency key, so an activity retry never counts the episode twice,
    for example as both `emitted` and `cap`.
    """
    try:
        return bool(get_client().set(_outcome_key(source_id), 1, nx=True, ex=_OUTCOME_KEY_TTL_SECONDS))
    except RedisError:
        # Without Redis the cap fails closed as `cap_unavailable`. Counting that drop twice beats losing it.
        return True


def _resumes_interrupted_episode(alert: AlertConfiguration, alert_check: AlertCheck) -> bool:
    """Whether the checks before this one, ignoring errored checks, end in a firing check.

    A failed query says nothing about the metric. Without this read, a transient error during an
    incident would look like a new firing episode, and the incident would file a second signal.
    """
    last_state = (
        AlertCheck.objects.filter(alert_configuration=alert)
        .exclude(id=alert_check.id)
        .exclude(state=AlertState.ERRORED)
        .order_by("-created_at")
        .values_list("state", flat=True)
        .first()
    )
    return last_state == AlertState.FIRING


def _legacy_episode(alert: AlertConfiguration, alert_check: AlertCheck) -> AlertFiringEpisode:
    return AlertFiringEpisode(
        team=alert.team,
        alert_id=str(alert.id),
        alert_check_id=str(alert_check.id),
        alert_name=alert.name,
        insight=alert.insight,
        detector_config=alert.detector_config,
        investigated=investigates(alert, firing=True),
        episode_started_at=alert_check.created_at,
        triggered_dates=alert_check.triggered_dates if isinstance(alert_check.triggered_dates, list) else None,
    )


def _prepare(
    episode: AlertFiringEpisode, breaches: list[str], *, resumes_interrupted_episode: Callable[[], bool]
) -> tuple[AlertFiringSkipReason | None, AlertFiringSignal | None]:
    team = episode.team
    source = get_source_config(team_id=team.id, source_product=SIGNAL_SOURCE_PRODUCT, source_type=_SOURCE_CONFIG_TYPE)
    if source is None or not source.enabled:
        return AlertFiringSkipReason.SOURCE_DISABLED, None
    if get_analytics_alert_scope(team_id=team.id) != _ALL_FIRING_ALERTS:
        return AlertFiringSkipReason.SCOPE, None
    if resumes_interrupted_episode():
        return AlertFiringSkipReason.NOT_NEW_EPISODE, None
    filter_outcome = evaluate_alert_filter(
        get_analytics_alert_name_patterns(team_id=team.id),
        alert_name=episode.alert_name,
        insight_name=episode.insight.name or episode.insight.derived_name,
    )
    if filter_outcome == AlertFilterOutcome.INVALID:
        return AlertFiringSkipReason.FILTER_INVALID, None
    if filter_outcome != AlertFilterOutcome.PASSED:
        return AlertFiringSkipReason.FILTERED, None

    # `emit_signal` reads the organization for its consent gate. Loading it here keeps that read off the event loop.
    team.organization  # noqa: B018
    signal = AlertFiringSignal(
        team=team,
        alert_id=episode.alert_id,
        alert_check_id=episode.alert_check_id,
        description=build_signal_description(episode, breaches),
        extra=build_signal_extra(episode, breaches),
    )
    # Charged last, so a failure above spends no token.
    decision = consume(cap_key(team.id), CAP_BUDGET)
    if isinstance(decision, BucketUnavailable):
        # Fails closed: the cap exists to bound spend during the rollout, and the signal is best effort.
        return AlertFiringSkipReason.CAP_UNAVAILABLE, None
    if not decision.allowed:
        return AlertFiringSkipReason.CAP, None
    return None, signal


def _detector_type(episode: AlertFiringEpisode) -> str:
    return (episode.detector_config or {}).get("type") or "threshold"


def build_signal_extra(episode: AlertFiringEpisode, breaches: list[str]) -> dict:
    insight = episode.insight
    triggered_dates = episode.triggered_dates
    extra = AnalyticsAlertFiringSignalExtra(
        alert_id=episode.alert_id,
        alert_name=episode.alert_name or "Unnamed alert",
        insight_id=str(insight.id),
        alert_check_id=episode.alert_check_id,
        detector_type=_detector_type(episode),
        breaches=breaches[:_MAX_BREACHES],
        episode_started_at=episode.episode_started_at.isoformat(),
        url=absolute_uri(f"/project/{episode.team.id}/insights/{insight.short_id}?alert_id={episode.alert_id}"),
        insight_name=insight.name or None,
        insight_short_id=insight.short_id or None,
        triggered_dates=[str(date) for date in triggered_dates] if triggered_dates else None,
    )
    return extra.model_dump(exclude_none=True)


def build_signal_description(episode: AlertFiringEpisode, breaches: list[str]) -> str:
    """Human-readable text embedded for grouping. It names the alert and the insight, then the breaches."""
    insight = episode.insight
    metric = f" on {insight.name}" if insight.name else ""
    insight_ref = f"{insight.short_id} / id {insight.id}" if insight.short_id else f"id {insight.id}"
    lines = [
        f"Insight alert '{episode.alert_name or 'Unnamed alert'}'{metric} started firing.",
        f"Insight: {insight_ref}. Detector: {_detector_type(episode)}.",
    ]
    if breaches:
        lines.append("Breaches:")
        lines.extend(f"- {breach}" for breach in breaches[:_MAX_BREACHES])
    description = "\n".join(lines)
    if len(description) > _MAX_DESCRIPTION_CHARS:
        description = description[: _MAX_DESCRIPTION_CHARS - 1].rstrip() + "…"
    return description
