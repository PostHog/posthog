"""Synchronous investigation for firing metrics alerts.

When a threshold alert on a metrics insight transitions into FIRING and the
alert has the investigation agent enabled, the metrics facade investigates the
window around the fire and the outcome lands on the AlertCheck's existing
investigation fields — so the alert page carries the why, not just the that.
Distinct from the detector alerts' agent workflow: this is a bounded set of
metric queries, run in-line with the check, no agent or notebook involved.
"""

from typing import TYPE_CHECKING

import structlog

from posthog.schema import AlertState, NodeKind

from posthog.utils import get_from_dict_or_attr

from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration

if TYPE_CHECKING:
    from products.metrics.backend.facade.contracts import InvestigationResult

logger = structlog.get_logger(__name__)


def should_investigate_metrics_alert(
    alert: AlertConfiguration,
    *,
    previous_state: str | None,
    new_state: str,
) -> bool:
    """True when this check should get a synchronous metrics investigation:
    a threshold (non-detector) alert on a metrics insight, opted in via the
    investigation flag, on a transition into FIRING (not on every re-fire)."""
    if not alert.investigation_agent_enabled or alert.detector_config:
        return False
    if previous_state == AlertState.FIRING or new_state != AlertState.FIRING:
        return False
    return alert.insight.alertable_query_kind == NodeKind.METRICS_QUERY


def run_metrics_alert_investigation(alert: AlertConfiguration, alert_check: AlertCheck) -> None:
    """Investigate the fired metric and persist the outcome on the check.

    Never raises: an investigation failure is recorded on the check and must
    not affect the alert's state or its notifications. Run OUTSIDE the check's
    persistence transaction — this issues ClickHouse queries.
    """
    try:
        summary = _run_investigation(alert, alert_check)
        alert_check.investigation_status = "done"
        alert_check.investigation_summary = summary
        alert_check.save(update_fields=["investigation_status", "investigation_summary"])
    except Exception as error:
        logger.exception("metrics_alert_investigation_failed", alert_id=str(alert.id), error=str(error))
        alert_check.investigation_status = "failed"
        alert_check.investigation_error = str(error)[:1000]
        alert_check.save(update_fields=["investigation_status", "investigation_error"])


def _run_investigation(alert: AlertConfiguration, alert_check: AlertCheck) -> str:
    # Deferred: the facade pulls in HogQL machinery that must stay off the
    # alerts import path (matching how core defers facade.queries).
    from products.metrics.backend.facade.api import investigate_incident  # noqa: PLC0415
    from products.metrics.backend.facade.contracts import IncidentContext  # noqa: PLC0415

    metric_name, service_name = _metric_and_service_from_insight(alert)
    result = investigate_incident(
        team=alert.team,
        context=IncidentContext(
            metric_name=metric_name,
            fired_at=alert_check.created_at,
            service_name=service_name,
        ),
    )
    return _summarize(result)


def _metric_and_service_from_insight(alert: AlertConfiguration) -> tuple[str, str | None]:
    query = alert.insight.query or {}
    clauses = get_from_dict_or_attr(query, "clauses") or []
    if not clauses:
        raise ValueError("Metrics insight has no clauses to investigate")
    first = clauses[0]
    metric_name = get_from_dict_or_attr(first, "metricName")
    if not metric_name:
        raise ValueError("Metrics insight clause has no metric name to investigate")
    service_name: str | None = None
    for filter_ in get_from_dict_or_attr(first, "filters") or []:
        key = get_from_dict_or_attr(filter_, "key")
        op = get_from_dict_or_attr(filter_, "op") or "eq"
        if key in ("service.name", "service_name") and op == "eq":
            service_name = get_from_dict_or_attr(filter_, "value")
            break
    return metric_name, service_name


def _summarize(result: "InvestigationResult") -> str:
    """A compact human summary of the InvestigationResult for the check record.

    Kept plain-text and short: it renders in the alert page's investigation
    section and in notification surfaces that only carry a sentence or two.
    """
    symptom = result.symptom
    change = f"{symptom.change_ratio:.1f}x" if symptom.baseline_mean else "from a zero baseline"
    lines = [
        f"{result.metric_name} moved {symptom.direction} to {symptom.anomaly_mean:.2f} "
        f"(baseline {symptom.baseline_mean:.2f}, {change})"
        + (f", starting around {symptom.onset_time}" if symptom.onset_time else "")
        + f". Blast radius: {result.blast_radius}; confidence: {result.confidence}."
    ]
    movers = ", ".join(f"{mover.key}={mover.label}" for mover in symptom.top_movers[:3])
    if movers:
        lines.append(f"Top movers: {movers}.")
    companions = ", ".join(f"{companion.metric_name} {companion.direction}" for companion in result.companions[:3])
    if companions:
        lines.append(f"Companions: {companions}.")
    return " ".join(lines)
