"""Synchronous investigation for firing metrics alerts.

When a threshold alert on a metrics insight transitions into FIRING and the
alert has the investigation agent enabled, the metrics facade investigates the
window around the fire and the outcome lands on the AlertCheck's existing
investigation fields — so the alert page carries the why, not just the that.
Distinct from the detector alerts' agent workflow: this is a bounded set of
metric queries, run in-line with the check, no agent or notebook involved.

Frequency is bounded by the same per-alert cooldown the detector path uses
(`claim_investigation_slot`), which the caller claims inside the check's
transaction; the run itself happens outside that transaction because it issues
ClickHouse queries and must never hold the row lock or affect the check outcome.
"""

import math
from typing import TYPE_CHECKING, Any, NamedTuple

import structlog

from posthog.schema import AlertState, NodeKind

from posthog.utils import get_from_dict_or_attr

from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration, InvestigationStatus

if TYPE_CHECKING:
    from products.metrics.backend.facade.contracts import InvestigationResult

logger = structlog.get_logger(__name__)

# Each target costs a handful of synchronous ClickHouse queries in the
# alert-evaluation path, so multi-clause investigations stay bounded.
MAX_INVESTIGATED_CLAUSES = 3
# Mover keys and labels come from ingested telemetry, so the persisted summary
# is capped rather than trusting label sizes.
MAX_SUMMARY_LENGTH = 4000

_SERVICE_FILTER_KEYS = ("service.name", "service_name")


class _InvestigationTarget(NamedTuple):
    metric_name: str
    service_name: str | None
    # The op of a service filter no single service could be derived from
    # (anything but eq) — surfaced as a caveat on the summary.
    unscoped_service_op: str | None


def should_investigate_metrics_alert(
    alert: AlertConfiguration,
    *,
    previous_state: str | None,
    new_state: str,
) -> bool:
    """True when this check is eligible for a synchronous metrics investigation:
    a threshold (non-detector) alert on a metrics insight, opted in via the
    investigation flag, on a transition into FIRING (not on every re-fire).

    Cooldown is enforced separately by `claim_investigation_slot`, mirroring the
    detector path. Never raises — an unexpected error reading the insight kind
    must not break the alert-evaluation path, so it degrades to "don't
    investigate".
    """
    if not alert.investigation_agent_enabled or alert.detector_config:
        return False
    if previous_state == AlertState.FIRING or new_state != AlertState.FIRING:
        return False
    try:
        return alert.insight.alertable_query_kind == NodeKind.METRICS_QUERY
    except Exception:
        logger.exception("metrics_alert_investigation_gate_failed", alert_id=str(alert.id))
        return False


def run_metrics_alert_investigation(alert: AlertConfiguration, alert_check: AlertCheck) -> None:
    """Investigate the fired metric and persist the outcome on the check.

    Never raises: an investigation failure is recorded on the check and must
    not affect the alert's state or its notifications. Run OUTSIDE the check's
    persistence transaction — this issues ClickHouse queries.
    """
    try:
        summary = _run_investigation(alert, alert_check)
        alert_check.investigation_status = InvestigationStatus.DONE
        alert_check.investigation_summary = summary
        alert_check.save(update_fields=["investigation_status", "investigation_summary"])
    except Exception as error:
        logger.exception("metrics_alert_investigation_failed", alert_id=str(alert.id), error=str(error))
        alert_check.investigation_status = InvestigationStatus.FAILED
        alert_check.investigation_error = {"message": str(error)[:1000]}
        alert_check.save(update_fields=["investigation_status", "investigation_error"])


def _run_investigation(alert: AlertConfiguration, alert_check: AlertCheck) -> str:
    # Deferred: the facade pulls in HogQL machinery that must stay off the
    # alerts import path (matching how core defers facade.queries).
    from products.metrics.backend.facade.api import investigate_incident  # noqa: PLC0415
    from products.metrics.backend.facade.contracts import IncidentContext  # noqa: PLC0415

    summaries: list[str] = []
    for target in _investigation_targets(alert):
        result = investigate_incident(
            team=alert.team,
            context=IncidentContext(
                metric_name=target.metric_name,
                fired_at=alert_check.created_at,
                service_name=target.service_name,
            ),
        )
        summary = _summarize(result)
        if target.unscoped_service_op:
            summary += (
                f" (The alert filters service.name with '{target.unscoped_service_op}', which does not pin "
                "down a single service, so this investigation ran across all services.)"
            )
        summaries.append(summary)
    return " ".join(summaries)[:MAX_SUMMARY_LENGTH]


def _investigation_targets(alert: AlertConfiguration) -> list[_InvestigationTarget]:
    """The (metric, service) pairs to investigate for this alert.

    The check records a single fired value with no pointer to the clause that
    breached (a formula query doesn't even evaluate clauses separately), so
    every distinct clause target is investigated — bounded by
    MAX_INVESTIGATED_CLAUSES — rather than assuming the first clause is the
    one that moved.
    """
    query = alert.insight.query or {}
    clauses = get_from_dict_or_attr(query, "clauses") or []
    if not clauses:
        raise ValueError("Metrics insight has no clauses to investigate")
    targets: list[_InvestigationTarget] = []
    seen: set[tuple[str, str | None]] = set()
    for clause in clauses:
        metric_name = get_from_dict_or_attr(clause, "metricName")
        if not metric_name:
            continue
        service_name, unscoped_service_op = _service_scope(clause)
        if (metric_name, service_name) in seen:
            continue
        seen.add((metric_name, service_name))
        targets.append(_InvestigationTarget(metric_name, service_name, unscoped_service_op))
        if len(targets) == MAX_INVESTIGATED_CLAUSES:
            break
    if not targets:
        raise ValueError("Metrics insight clauses have no metric name to investigate")
    return targets


def _service_scope(clause: Any) -> tuple[str | None, str | None]:
    """The clause's service scope: (service to investigate, underivable op).

    The metrics filter ops are eq/neq/regex/not_regex over a single value, so
    only an eq filter pins down the one service to scope the investigation to.
    Any other service filter can't be applied (IncidentContext scopes by exact
    service), so its op is reported back for a summary caveat instead of
    silently investigating globally.
    """
    unscoped_op: str | None = None
    for filter_ in get_from_dict_or_attr(clause, "filters") or []:
        if get_from_dict_or_attr(filter_, "key") not in _SERVICE_FILTER_KEYS:
            continue
        op = get_from_dict_or_attr(filter_, "op") or "eq"
        value = get_from_dict_or_attr(filter_, "value")
        if op == "eq" and value:
            return value, None
        unscoped_op = unscoped_op or op
    return None, unscoped_op


def _summarize(result: "InvestigationResult") -> str:
    """A compact human summary of the InvestigationResult for the check record.

    Kept plain-text and short: it renders in the alert page's investigation
    section and in notification surfaces that only carry a sentence or two.
    """
    symptom = result.symptom
    no_movement = symptom.direction == "flat" or (symptom.baseline_mean == 0 and symptom.anomaly_mean == 0)
    if no_movement:
        headline = f"{result.metric_name} showed no significant movement in the window"
    else:
        if symptom.baseline_mean and math.isfinite(symptom.change_ratio):
            change = f"{symptom.change_ratio:.1f}x"
        else:
            change = "from a near-zero baseline"
        headline = (
            f"{result.metric_name} moved {symptom.direction} to {symptom.anomaly_mean:.2f} "
            f"(baseline {symptom.baseline_mean:.2f}, {change})"
            + (f", starting around {symptom.onset_time}" if symptom.onset_time else "")
        )
    lines = [f"{headline}. Blast radius: {result.blast_radius}; confidence: {result.confidence}."]
    movers = ", ".join(f"{mover.key}={mover.label}" for mover in symptom.top_movers[:3])
    if movers:
        lines.append(f"Top movers: {movers}.")
    companions = ", ".join(f"{companion.metric_name} {companion.direction}" for companion in result.companions[:3])
    if companions:
        lines.append(f"Companions: {companions}.")
    return " ".join(lines)
