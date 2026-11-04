"""Inbox signals for insight alerts that start to fire without the investigation agent.

The investigation agent emits its own `analytics` / `anomaly_investigation` signal after the verdict.
This path covers the alerts it never investigates, for teams whose product analytics source has the
`all_firing_alerts` scope. It emits one signal per firing episode, from the check that starts it.
"""

from __future__ import annotations

import enum

import structlog
from asgiref.sync import async_to_sync

from posthog.schema import AlertState

from posthog.temporal.alerts.investigation import investigates
from posthog.token_bucket import BucketUnavailable, Budget, consume, refund
from posthog.utils import absolute_uri

from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration
from products.signals.backend.facade.api import emit_signal
from products.signals.backend.facade.signal_extras import AnalyticsAlertFiringSignalExtra
from products.signals.backend.facade.source_configs import get_analytics_alert_scope, get_source_config

logger = structlog.get_logger(__name__)

SIGNAL_SOURCE_PRODUCT = "analytics"
SIGNAL_SOURCE_TYPE = "alert_firing"
# The product analytics source row. Its `enabled` flag and `alert_scope` key govern this signal too.
_SOURCE_CONFIG_TYPE = "anomaly_investigation"
_ALL_FIRING_ALERTS = "all_firing_alerts"

# Rollout cap per team: a burst of 20 episodes, then about one per hour. Each signal costs a pipeline
# run, and a team with many noisy alerts must not flood its inbox or our spend.
CAP_BUDGET = Budget(burst=20, per_hour=1)

# Same margin under the facade's description token limit as the investigation signal.
_MAX_DESCRIPTION_CHARS = 3000
_MAX_BREACHES = 20


class AlertFiringSkipReason(enum.StrEnum):
    NOT_NEW_EPISODE = "not_new_episode"
    INVESTIGATED = "investigated"
    SOURCE_DISABLED = "source_disabled"
    SCOPE = "scope"
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


def emit_alert_firing_signal(
    alert: AlertConfiguration, alert_check: AlertCheck, *, previous_state: str, breaches: list[str] | None
) -> bool:
    """Emit the signal when every gate passes. Returns whether it was dispatched. Never raises.

    Call it after the check is committed, outside the alert row lock. A failure here must not change
    the check, its notification or the alert state.
    """
    try:
        skip_reason = _emit(alert, alert_check, previous_state=previous_state, breaches=breaches or [])
    except Exception:
        logger.exception(
            "alert_firing.signal_emission_failed", alert_id=str(alert.id), alert_check_id=str(alert_check.id)
        )
        return False
    if skip_reason in _UNLOGGED_SKIP_REASONS:
        return False
    if skip_reason is not None:
        logger.info(
            "alert_firing.signal_skipped",
            alert_id=str(alert.id),
            alert_check_id=str(alert_check.id),
            reason=skip_reason.value,
        )
        return False
    logger.info("alert_firing.signal_emitted", alert_id=str(alert.id), alert_check_id=str(alert_check.id))
    return True


def _emit(
    alert: AlertConfiguration, alert_check: AlertCheck, *, previous_state: str, breaches: list[str]
) -> AlertFiringSkipReason | None:
    skip_reason = alert_firing_skip_reason(alert, previous_state=previous_state, new_state=alert_check.state)
    if skip_reason is not None:
        return skip_reason
    source = get_source_config(
        team_id=alert.team_id, source_product=SIGNAL_SOURCE_PRODUCT, source_type=_SOURCE_CONFIG_TYPE
    )
    if source is None or not source.enabled:
        return AlertFiringSkipReason.SOURCE_DISABLED
    if get_analytics_alert_scope(team_id=alert.team_id) != _ALL_FIRING_ALERTS:
        return AlertFiringSkipReason.SCOPE

    decision = consume(cap_key(alert.team_id), CAP_BUDGET)
    if isinstance(decision, BucketUnavailable):
        # Fails closed: the cap exists to bound spend during the rollout, and the signal is best effort.
        return AlertFiringSkipReason.CAP_UNAVAILABLE
    if not decision.allowed:
        return AlertFiringSkipReason.CAP

    source_id = f"{alert.id}:{alert_check.id}"
    try:
        dispatched = async_to_sync(emit_signal)(
            team=alert.team,
            source_product=SIGNAL_SOURCE_PRODUCT,
            source_type=SIGNAL_SOURCE_TYPE,
            source_id=source_id,
            # Same key on a retried evaluation, so one episode starts at most one emission.
            idempotency_key=source_id,
            description=build_signal_description(alert, breaches),
            weight=1,
            extra=build_signal_extra(alert, alert_check, breaches),
        )
    except Exception:
        refund(cap_key(alert.team_id), CAP_BUDGET)
        raise
    if not dispatched:
        refund(cap_key(alert.team_id), CAP_BUDGET)
        return AlertFiringSkipReason.NOT_DISPATCHED
    return None


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
