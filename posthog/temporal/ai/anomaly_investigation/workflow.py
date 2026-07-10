"""Temporal workflow that kicks off the anomaly investigation agent and persists
its findings as a Notebook linked to the AlertCheck.

Triggered from posthog/temporal/alerts/workflows.py when an alert transitions to FIRING.
"""

from __future__ import annotations

import json
import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from django.db import transaction
from django.utils import timezone

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.models import Team, User
from posthog.tasks.alerts.utils import dispatch_alert_notification, record_alert_delivery
from posthog.temporal.ai.anomaly_investigation.charts import png_to_b64, render_series_chart
from posthog.temporal.ai.anomaly_investigation.notebook import NotebookRenderContext, build_investigation_notebook
from posthog.temporal.ai.anomaly_investigation.prompts import build_anomaly_context
from posthog.temporal.ai.anomaly_investigation.report import InvestigationReport
from posthog.temporal.ai.anomaly_investigation.runner import run_investigation
from posthog.temporal.ai.anomaly_investigation.tools import _run_detector_simulation
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.utils import absolute_uri

from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration, InvestigationStatus
from products.notebooks.backend.facade import api as notebooks
from products.signals.backend.facade import api as signals

if TYPE_CHECKING:
    from products.product_analytics.backend.models.insight import Insight

logger = structlog.get_logger(__name__)

# (source_product, source_type) identifiers for the emitted signal. The signals taxonomy, payload
# contract, and inbox support for this pair are added in a separate PR; this module only emits.
SIGNAL_SOURCE_PRODUCT = "analytics"
SIGNAL_SOURCE_TYPE = "anomaly_investigation"


ANOMALY_INVESTIGATION_ACTIVITY_START_TO_CLOSE = 20 * 60  # 20 minutes
ANOMALY_INVESTIGATION_ACTIVITY_HEARTBEAT_TIMEOUT = 5 * 60  # 5 minutes
ANOMALY_INVESTIGATION_ACTIVITY_MAX_ATTEMPTS = 2

MAX_SUMMARY_CHARS = 500

# Cap for the embedded signal description. Kept well under the signals facade's ~8000-token limit
# (a conservative margin even for token-dense text) so a long agent report can't get the signal
# rejected and silently dropped.
_MAX_DESCRIPTION_CHARS = 3000


@dataclass
class AnomalyInvestigationWorkflowInputs:
    team_id: int
    alert_id: UUID
    alert_check_id: UUID
    user_id: Optional[int] = None
    trace_id: Optional[str] = None


@workflow.defn(name="anomaly-investigation")
class AnomalyInvestigationWorkflow(PostHogWorkflow):
    """Single-activity workflow — the heavy lifting happens inside the activity."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> AnomalyInvestigationWorkflowInputs:
        loaded = json.loads(inputs[0])
        return AnomalyInvestigationWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: AnomalyInvestigationWorkflowInputs) -> None:
        await workflow.execute_activity(
            investigate_anomaly_activity,
            inputs,
            start_to_close_timeout=timedelta(seconds=ANOMALY_INVESTIGATION_ACTIVITY_START_TO_CLOSE),
            heartbeat_timeout=timedelta(seconds=ANOMALY_INVESTIGATION_ACTIVITY_HEARTBEAT_TIMEOUT),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                maximum_interval=timedelta(minutes=1),
                maximum_attempts=ANOMALY_INVESTIGATION_ACTIVITY_MAX_ATTEMPTS,
            ),
        )


@activity.defn
async def investigate_anomaly_activity(inputs: AnomalyInvestigationWorkflowInputs) -> None:
    team, alert, alert_check = await asyncio.gather(
        Team.objects.aget(id=inputs.team_id),
        AlertConfiguration.objects.select_related("insight").aget(id=inputs.alert_id),
        AlertCheck.objects.aget(id=inputs.alert_check_id),
    )

    user: User | None = None
    if inputs.user_id is not None:
        try:
            user = await User.objects.aget(id=inputs.user_id)
        except User.DoesNotExist:
            user = None
    if user is None:
        user = await _pick_investigation_user(alert)

    if user is None:
        await _mark_failed(alert_check, "No user available to run the investigation agent.")
        return

    await _update_status(alert_check, InvestigationStatus.RUNNING)

    insight = alert.insight
    metric_description = insight.name or f"Insight {insight.short_id}"
    detector_type = (alert.detector_config or {}).get("type") or "threshold"

    anomaly_context_text = build_anomaly_context(
        alert_name=alert.name or "Unnamed alert",
        metric_description=metric_description,
        detector_type=detector_type,
        triggered_dates=list(alert_check.triggered_dates or []),
        triggered_metadata=alert_check.triggered_metadata,
        calculated_value=alert_check.calculated_value,
        interval=alert_check.interval,
    )

    # Render a chart of the metric with the detector's anomaly points marked and
    # attach it to the HumanMessage so the multimodal model can reason visually
    # before spending any tool-call budget.
    anomaly_context = await sync_to_async(_build_multimodal_context, thread_sensitive=False)(
        alert=alert,
        context_text=anomaly_context_text,
    )

    try:
        async with Heartbeater():
            result = await run_investigation(
                team=team,
                user=user,
                anomaly_context=anomaly_context,
                alert=alert,
                heartbeat=activity.heartbeat,
            )
    except Exception as err:
        logger.exception("anomaly_investigation.agent_failed", alert_id=str(alert.id))
        await _mark_failed(alert_check, f"Agent run failed: {err}")
        raise

    notebook_content = build_investigation_notebook(
        NotebookRenderContext(
            alert=alert,
            alert_check=alert_check,
            insight=insight,
            report=result.report,
        )
    )

    notebook = await sync_to_async(notebooks.create_notebook, thread_sensitive=False)(
        team.id,
        title=f"Investigation — {alert.name or 'anomaly alert'}",
        content=notebook_content,
        text_content=result.report.summary,
        created_by_id=user.id,
        last_modified_by_id=user.id,
        creation_source=notebooks.NotebookCreationSource.TEMPORAL_AGENT,
    )

    summary_for_list = _truncate_summary(result.report.summary)
    await sync_to_async(AlertCheck.objects.filter(id=alert_check.id).update, thread_sensitive=False)(
        investigation_notebook_id=notebook.id,
        investigation_status=InvestigationStatus.DONE,
        investigation_verdict=result.report.verdict,
        investigation_summary=summary_for_list,
        investigation_error=None,
    )

    # Always invoke the dispatcher — it reads the check's own delivery state
    # (`notification_sent_at` / `notification_suppressed_by_agent`) as its
    # idempotency guard, so non-gated checks (already dispatched by the main
    # task) short-circuit safely. Calling unconditionally closes the race where
    # a user toggles `investigation_gates_notifications` from True → False
    # after the check was held back but before the workflow completes — in
    # that case the current flag would say "don't dispatch" even though the
    # notification was never sent.
    await sync_to_async(_dispatch_gated_notification, thread_sensitive=False)(
        alert=alert,
        alert_check=alert_check,
        verdict=result.report.verdict,
        summary=summary_for_list or "",
        notebook_short_id=notebook.short_id,
    )

    # Surface the completed investigation to the Signals inbox. Best-effort: the investigation
    # itself has already succeeded and been persisted, so a failure to emit must not fail the
    # activity (and trigger a re-run of the whole agent).
    try:
        await _emit_investigation_signal(
            team=team,
            alert=alert,
            alert_check=alert_check,
            insight=insight,
            detector_type=detector_type,
            report=result.report,
            notebook_short_id=notebook.short_id,
        )
    except Exception:
        logger.exception(
            "anomaly_investigation.signal_emission_failed",
            alert_id=str(alert.id),
            alert_check_id=str(alert_check.id),
        )


# Inbox weight per investigation verdict — true positives are the actionable ones and should be
# prioritized; false positives are low-signal noise the agent already dismissed.
_VERDICT_WEIGHTS: dict[str, float] = {
    "true_positive": 0.9,
    "inconclusive": 0.6,
    "false_positive": 0.3,
}


def _build_investigation_signal_extra(
    *,
    alert: AlertConfiguration,
    alert_check: AlertCheck,
    insight: Insight,
    detector_type: str,
    report: InvestigationReport,
    notebook_short_id: str | None,
) -> dict:
    """The `extra` payload for an anomaly-investigation signal — a plain dict validated against
    `AnomalyInvestigationSignalExtra` inside `emit_signal`."""
    notebook_url = absolute_uri(f"/notebooks/{notebook_short_id}") if notebook_short_id else absolute_uri("/alerts")
    extra: dict = {
        "alert_id": str(alert.id),
        "alert_name": alert.name or "Unnamed alert",
        "alert_check_id": str(alert_check.id),
        "insight_id": str(insight.id),
        "detector_type": detector_type,
        "verdict": report.verdict,
        "summary": report.summary,
        "hypotheses": [
            {"title": h.title, "rationale": h.rationale, "evidence": list(h.evidence)} for h in report.hypotheses
        ],
        "recommendations": list(report.recommendations),
        "tool_calls_used": report.tool_calls_used,
        "url": notebook_url,
    }
    # Optional fields — omit when absent so the schema's None defaults apply.
    if insight.name:
        extra["insight_name"] = insight.name
    insight_short_id = getattr(insight, "short_id", None)
    if insight_short_id:
        extra["insight_short_id"] = insight_short_id
    if alert_check.triggered_dates:
        extra["triggered_dates"] = list(alert_check.triggered_dates)
    if notebook_short_id:
        extra["notebook_short_id"] = notebook_short_id
    return extra


async def _emit_investigation_signal(
    *,
    team: Team,
    alert: AlertConfiguration,
    alert_check: AlertCheck,
    insight: Insight,
    detector_type: str,
    report: InvestigationReport,
    notebook_short_id: str | None,
) -> None:
    """Emit an `alerts/anomaly_investigation` signal carrying the agent's verdict and findings."""
    await signals.emit_signal(
        team=team,
        source_product=SIGNAL_SOURCE_PRODUCT,
        source_type=SIGNAL_SOURCE_TYPE,
        source_id=str(alert_check.id),
        description=_build_signal_description(
            alert_name=alert.name or "Unnamed alert",
            insight_name=insight.name or None,
            insight_id=str(insight.id),
            insight_short_id=getattr(insight, "short_id", None),
            report=report,
        ),
        weight=_VERDICT_WEIGHTS.get(report.verdict, 0.6),
        extra=_build_investigation_signal_extra(
            alert=alert,
            alert_check=alert_check,
            insight=insight,
            detector_type=detector_type,
            report=report,
            notebook_short_id=notebook_short_id,
        ),
    )


def _build_signal_description(
    *,
    alert_name: str,
    insight_name: str | None,
    insight_id: str,
    insight_short_id: str | None,
    report: InvestigationReport,
) -> str:
    """Human-readable description embedded for grouping. Leads with the verdict, names the insight
    (with its id, handy for lookups), then the agent's summary, hypotheses, and recommendations."""
    verdict_label = report.verdict.replace("_", " ")
    metric = f" on {insight_name}" if insight_name else ""
    insight_ref = f"{insight_short_id} / id {insight_id}" if insight_short_id else f"id {insight_id}"
    lines: list[str] = [
        f"Anomaly investigation for alert '{alert_name}'{metric} (verdict: {verdict_label}).",
        f"Insight: {insight_ref}.",
        report.summary,
    ]
    if report.hypotheses:
        lines.append("Hypotheses:")
        lines.extend(f"- {h.title}: {h.rationale}" for h in report.hypotheses)
    if report.recommendations:
        lines.append("Recommendations:")
        lines.extend(f"- {rec}" for rec in report.recommendations)
    description = "\n".join(line for line in lines if line)
    # Bound the agent-generated text so it can't blow the facade's description token limit — past it
    # emit_signal raises and the best-effort caller would silently drop the signal. The full write-up
    # lives in the linked notebook, so truncating the embedded description is safe.
    if len(description) > _MAX_DESCRIPTION_CHARS:
        description = description[: _MAX_DESCRIPTION_CHARS - 1].rstrip() + "…"
    return description


def _dispatch_gated_notification(
    *,
    alert,
    alert_check,
    verdict: str | None,
    summary: str,
    notebook_short_id: str | None,
) -> None:
    """Decide whether to fire the notification now that we have the verdict.

    - true_positive → notify (enriched body with verdict + summary + notebook link)
    - false_positive → suppress, mark the check so the UI can surface why
    - inconclusive → fall back to the alert's configured policy
    - unknown / null verdict → notify (safest default)

    Idempotent: if another codepath (retry, safety-net task) already dispatched,
    this is a no-op.
    """
    inconclusive_action = alert.investigation_inconclusive_action or "notify"
    suppress = verdict == "false_positive" or (verdict == "inconclusive" and inconclusive_action == "suppress")

    with transaction.atomic():
        # Re-fetch under a row lock so concurrent dispatchers can't double-notify.
        check = AlertCheck.objects.select_for_update().get(id=alert_check.id)
        if check.notification_sent_at is not None or check.notification_suppressed_by_agent:
            return

        if suppress:
            check.notification_suppressed_by_agent = True
            check.save(update_fields=["notification_suppressed_by_agent"])
            logger.info(
                "anomaly_investigation.notification_suppressed",
                alert_id=str(alert.id),
                alert_check_id=str(alert_check.id),
                verdict=verdict,
            )
            return

        breaches = _build_breach_descriptions(
            alert_check=check, verdict=verdict, summary=summary, notebook_short_id=notebook_short_id
        )
        try:
            targets = dispatch_alert_notification(alert, check, breaches)
            if targets is not None:
                record_alert_delivery(alert, check, targets)
        except Exception:
            logger.exception(
                "anomaly_investigation.gated_notification_failed",
                alert_id=str(alert.id),
                alert_check_id=str(alert_check.id),
            )
            # Don't swallow — let the safety-net task retry on the next tick.
            raise

        # Keep notification_sent_at updated in lock-step with the delivery so the
        # safety-net's idempotency check still trips on a successful workflow dispatch.
        check.notification_sent_at = timezone.now()
        check.save(update_fields=["notification_sent_at"])


def _build_breach_descriptions(
    *,
    alert_check,
    verdict: str | None,
    summary: str,
    notebook_short_id: str | None,
) -> list[str]:
    """Compose the strings that populate the `match_descriptions` list in the
    existing alert email template. Keeps the current template working while
    giving gated notifications richer body content.
    """
    lines: list[str] = []
    triggered_dates = alert_check.triggered_dates or []
    if triggered_dates:
        if len(triggered_dates) == 1:
            lines.append(f"Anomaly detected on {triggered_dates[0]}.")
        else:
            lines.append(f"Anomaly detected from {triggered_dates[0]} to {triggered_dates[-1]}.")
    elif alert_check.calculated_value is not None:
        lines.append(f"Calculated value at fire: {alert_check.calculated_value}.")
    else:
        lines.append("Anomaly detected.")

    verdict_label = {"true_positive": "True positive", "inconclusive": "Inconclusive"}.get(verdict or "", "")
    if verdict_label:
        lines.append(f"Investigation verdict: {verdict_label}.")
    if summary:
        lines.append(summary)
    if notebook_short_id:
        notebook_url = absolute_uri(f"/notebooks/{notebook_short_id}")
        lines.append(f"See {notebook_url} for the full investigation.")
    return lines


def _truncate_summary(summary: str | None) -> str | None:
    """Clamp the agent's summary for list rendering and email/Slack follow-ups.

    The full write-up already lives in the notebook — this field is just a teaser.
    """
    if not summary:
        return None
    trimmed = summary.strip()
    if not trimmed:
        return None
    if len(trimmed) <= MAX_SUMMARY_CHARS:
        return trimmed
    return trimmed[: MAX_SUMMARY_CHARS - 1].rstrip() + "…"


async def _update_status(alert_check, status: str) -> None:
    await sync_to_async(AlertCheck.objects.filter(id=alert_check.id).update, thread_sensitive=False)(
        investigation_status=status,
    )


async def _mark_failed(alert_check, reason: str) -> None:
    await sync_to_async(AlertCheck.objects.filter(id=alert_check.id).update, thread_sensitive=False)(
        investigation_status=InvestigationStatus.FAILED,
        investigation_error={"message": reason},
    )


def _build_multimodal_context(*, alert, context_text: str):
    """Return a LangChain HumanMessage content value — either a plain string or a
    list of content blocks with the text and a rendered chart PNG.

    Best-effort: if the detector can't simulate or the chart fails to render, we
    fall back to text-only so the investigation still runs.
    """
    if alert.detector_config is None or alert.insight is None:
        return context_text

    sim = _run_detector_simulation(alert=alert, team=alert.team, date_from=None)
    if isinstance(sim, str) or not sim:
        logger.info("anomaly_investigation.chart_skipped", alert_id=str(alert.id), reason=str(sim)[:120])
        return context_text

    dates = sim.get("dates") or []
    values = sim.get("data") or []
    if not dates or not values:
        return context_text

    png = render_series_chart(
        dates=dates,
        values=values,
        triggered_indices=sim.get("triggered_indices") or [],
        scores=sim.get("scores") or None,
        title=(alert.insight.name or alert.name or "Metric")[:80],
    )
    if not png:
        return context_text

    return [
        {"type": "text", "text": context_text},
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": png_to_b64(png),
            },
        },
    ]


async def _pick_investigation_user(alert) -> User | None:
    """Fall back to the alert creator, then any subscribed user, then None."""

    def _resolve() -> User | None:
        if alert.created_by_id:
            try:
                return User.objects.get(id=alert.created_by_id)
            except User.DoesNotExist:
                pass
        return alert.subscribed_users.first()

    return await sync_to_async(_resolve, thread_sensitive=False)()
