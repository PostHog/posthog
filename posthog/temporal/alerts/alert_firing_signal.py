"""Inbox signals for insight alerts that start to fire without the investigation agent.

The investigation agent emits its own `analytics` / `anomaly_investigation` signal after the verdict.
This path covers the alerts it never investigates, for teams whose product analytics source has the
`all_firing_alerts` scope. It emits one signal per firing episode, from the check that starts it.
"""

from __future__ import annotations

import enum
import asyncio

import structlog

from posthog.schema import AlertState

from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.temporal.alerts.investigation import investigates
from posthog.token_bucket import BucketUnavailable, Budget, consume, refund
from posthog.utils import absolute_uri

from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration
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


# Nearly every check fails one of these, so a log line for them would only be noise.
_UNLOGGED_SKIP_REASONS = frozenset({AlertFiringSkipReason.NOT_NEW_EPISODE, AlertFiringSkipReason.INVESTIGATED})


def cap_key(team_id: int) -> str:
    return f"signals_alert_firing_rate:{team_id}"


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
    try:
        skip_reason, signal = _prepare(alert, alert_check, previous_state=previous_state, breaches=breaches or [])
    except Exception:
        logger.exception(
            "alert_firing.signal_prepare_failed", alert_id=str(alert.id), alert_check_id=str(alert_check.id)
        )
        return None
    if skip_reason is not None and skip_reason not in _UNLOGGED_SKIP_REASONS:
        _log_skip(str(alert.id), str(alert_check.id), skip_reason)
    return signal


async def dispatch_alert_firing_signal(signal: AlertFiringSignal) -> bool:
    """Send a prepared signal. Returns whether it was dispatched. Never raises.

    Await it from the activity's event loop, not from a thread. `emit_signal` runs sync work on the
    default executor, so a call that blocks an executor thread on it can deadlock once every executor
    thread waits the same way. A failure never changes the committed check.
    """
    source_id = f"{signal.alert_id}:{signal.alert_check_id}"
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
        return True
    await asyncio.to_thread(refund, cap_key(signal.team.id), CAP_BUDGET)
    if dispatched is False:
        _log_skip(signal.alert_id, signal.alert_check_id, AlertFiringSkipReason.NOT_DISPATCHED)
    return False


def _log_skip(alert_id: str, alert_check_id: str, reason: AlertFiringSkipReason) -> None:
    logger.info("alert_firing.signal_skipped", alert_id=alert_id, alert_check_id=alert_check_id, reason=reason.value)


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


def _prepare(
    alert: AlertConfiguration, alert_check: AlertCheck, *, previous_state: str, breaches: list[str]
) -> tuple[AlertFiringSkipReason | None, AlertFiringSignal | None]:
    skip_reason = alert_firing_skip_reason(alert, previous_state=previous_state, new_state=alert_check.state)
    if skip_reason is not None:
        return skip_reason, None
    source = get_source_config(
        team_id=alert.team_id, source_product=SIGNAL_SOURCE_PRODUCT, source_type=_SOURCE_CONFIG_TYPE
    )
    if source is None or not source.enabled:
        return AlertFiringSkipReason.SOURCE_DISABLED, None
    if get_analytics_alert_scope(team_id=alert.team_id) != _ALL_FIRING_ALERTS:
        return AlertFiringSkipReason.SCOPE, None
    if previous_state == AlertState.ERRORED and _resumes_interrupted_episode(alert, alert_check):
        return AlertFiringSkipReason.NOT_NEW_EPISODE, None
    filter_outcome = evaluate_alert_filter(
        get_analytics_alert_name_patterns(team_id=alert.team_id),
        alert_name=alert.name,
        insight_name=alert.insight.name or alert.insight.derived_name,
    )
    if filter_outcome == AlertFilterOutcome.INVALID:
        return AlertFiringSkipReason.FILTER_INVALID, None
    if filter_outcome != AlertFilterOutcome.PASSED:
        return AlertFiringSkipReason.FILTERED, None

    team = alert.team
    # `emit_signal` reads the organization for its consent gate. Loading it here keeps that read off the event loop.
    team.organization  # noqa: B018
    signal = AlertFiringSignal(
        team=team,
        alert_id=str(alert.id),
        alert_check_id=str(alert_check.id),
        description=build_signal_description(alert, breaches),
        extra=build_signal_extra(alert, alert_check, breaches),
    )
    # Charged last, so a failure above spends no token.
    decision = consume(cap_key(alert.team_id), CAP_BUDGET)
    if isinstance(decision, BucketUnavailable):
        # Fails closed: the cap exists to bound spend during the rollout, and the signal is best effort.
        return AlertFiringSkipReason.CAP_UNAVAILABLE, None
    if not decision.allowed:
        return AlertFiringSkipReason.CAP, None
    return None, signal


def _detector_type(alert: AlertConfiguration) -> str:
    return (alert.detector_config or {}).get("type") or "threshold"


def build_signal_extra(alert: AlertConfiguration, alert_check: AlertCheck, breaches: list[str]) -> dict:
    insight = alert.insight
    triggered_dates = alert_check.triggered_dates
    extra = AnalyticsAlertFiringSignalExtra(
        alert_id=str(alert.id),
        alert_name=alert.name or "Unnamed alert",
        insight_id=str(insight.id),
        alert_check_id=str(alert_check.id),
        detector_type=_detector_type(alert),
        breaches=breaches[:_MAX_BREACHES],
        episode_started_at=alert_check.created_at.isoformat(),
        url=absolute_uri(f"/project/{alert.team_id}/insights/{insight.short_id}?alert_id={alert.id}"),
        insight_name=insight.name or None,
        insight_short_id=insight.short_id or None,
        triggered_dates=(
            [str(date) for date in triggered_dates] if isinstance(triggered_dates, list) and triggered_dates else None
        ),
    )
    return extra.model_dump(exclude_none=True)


def build_signal_description(alert: AlertConfiguration, breaches: list[str]) -> str:
    """Human-readable text embedded for grouping. It names the alert and the insight, then the breaches."""
    insight = alert.insight
    metric = f" on {insight.name}" if insight.name else ""
    insight_ref = f"{insight.short_id} / id {insight.id}" if insight.short_id else f"id {insight.id}"
    lines = [
        f"Insight alert '{alert.name or 'Unnamed alert'}'{metric} started firing.",
        f"Insight: {insight_ref}. Detector: {_detector_type(alert)}.",
    ]
    if breaches:
        lines.append("Breaches:")
        lines.extend(f"- {breach}" for breach in breaches[:_MAX_BREACHES])
    description = "\n".join(lines)
    if len(description) > _MAX_DESCRIPTION_CHARS:
        description = description[: _MAX_DESCRIPTION_CHARS - 1].rstrip() + "…"
    return description
