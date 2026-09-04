"""Temporal workflow that kicks off the anomaly investigation agent and persists
its findings as a Notebook linked to the AlertCheck.

Triggered from posthog/temporal/alerts/workflows.py for a firing check the budget allows.
"""

from __future__ import annotations

import re
import json
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from django.db import transaction

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.models import Team, User
from posthog.tasks.alerts.utils import INSIGHT_ALERT_FIRING_EVENT, dispatch_alert_notification, record_alert_delivery
from posthog.temporal.ai.anomaly_investigation.charts import png_to_b64, render_series_chart
from posthog.temporal.ai.anomaly_investigation.metric_definition import describe_metric_definition
from posthog.temporal.ai.anomaly_investigation.notebook import NotebookRenderContext, build_investigation_notebook
from posthog.temporal.ai.anomaly_investigation.prompts import build_anomaly_context
from posthog.temporal.ai.anomaly_investigation.report import InvestigationReport
from posthog.temporal.ai.anomaly_investigation.runner import run_investigation
from posthog.temporal.ai.anomaly_investigation.tools import _run_detector_simulation
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.utils import absolute_uri

from products.alerts.backend.destinations import list_active_alert_destinations
from products.alerts.backend.investigation_episode import EpisodeInvestigations, episode_investigations
from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration, InvestigationStatus
from products.exports.backend.facade import api as exports
from products.notebooks.backend.facade import api as notebooks
from products.signals.backend.facade import api as signals

if TYPE_CHECKING:
    from products.product_analytics.backend.facade.models import Insight

logger = structlog.get_logger(__name__)

# (source_product, source_type) identifiers for the emitted signal. The signals taxonomy, payload
# contract, and inbox support for this pair are added in a separate PR; this module only emits.
SIGNAL_SOURCE_PRODUCT = "analytics"
SIGNAL_SOURCE_TYPE = "anomaly_investigation"


# Sized to cover a realistic worst-case sequential agent run: up to MAX_TOOL_CALLS + 2 LLM turns
# (tool loop, finalize, and one corrective finalize retry), each capped at the runner's per-request
# timeout (thinking turns run long). 20 min got tight once that per-request timeout rose to 180s,
# so a slow thinking-heavy run could blow the deadline and be killed mid-flight — skipping the
# runner's fallback path and re-running the whole agent; the finalize retry pushed the 12-request
# worst case to 36 min, past the previous 30. 40 min keeps a realistic run inside a single activity
# attempt; the pathological tail falls to the retry.
ANOMALY_INVESTIGATION_ACTIVITY_START_TO_CLOSE = 40 * 60  # 40 minutes
ANOMALY_INVESTIGATION_ACTIVITY_HEARTBEAT_TIMEOUT = 5 * 60  # 5 minutes
ANOMALY_INVESTIGATION_ACTIVITY_MAX_ATTEMPTS = 2

MAX_SUMMARY_CHARS = 500

_VERDICT_LABELS = {
    "true_positive": "True positive",
    "false_positive": "False positive",
    "inconclusive": "Inconclusive",
}

# Marker on the check's delivery receipts: the follow-up for a changed verdict is sent once.
_VERDICT_CHANGE_FOLLOWUP_KEY = "investigation_verdict_change"

# Cap for the embedded signal description. Kept well under the signals facade's ~8000-token limit
# (a conservative margin even for token-dense text) so a long agent report can't get the signal
# rejected and silently dropped.
_MAX_DESCRIPTION_CHARS = 3000

# Matches a sentence-ending punctuation mark followed by whitespace or end-of-string,
# used to clip the summary teaser on a sentence boundary instead of mid-word.
_SENTENCE_END_RE = re.compile(r"[.!?](?=\s|$)")

# TTL for the tokenized chart URL embedded in Slack. Slack fetches the image at delivery,
# but the URL must stay resolvable while people scroll back to the message; 30 days matches
# the delivery-URL TTL used for task chart artifacts (products/tasks living_artifacts).
_INSIGHT_CHART_URL_TTL = timedelta(days=30)

# The stored PNG outlives its delivery URL by one day so the URL can never point at a
# deleted asset; without an explicit TTL the format default keeps the PNG for six months.
_INSIGHT_CHART_ASSET_TTL = timedelta(days=31)


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
        # The alerted series, not series 0 — matching how the check and the chart pick it.
        metric_definition=describe_metric_definition(
            insight.query, series_index=(alert.config or {}).get("series_index", 0)
        ),
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

    # Rendered before the check is marked DONE: once the status is terminal the safety net's
    # short grace applies (INVESTIGATION_NOTIFY_GRACE_MINUTES), and a slow render sitting
    # between the DONE update and the dispatch would let the sweep force-send its fallback
    # notification mid-render. While the status is RUNNING the sweep waits much longer.
    insight_chart_url = await sync_to_async(_prepare_insight_chart_url, thread_sensitive=False)(
        alert=alert,
        alert_check=alert_check,
        user=user,
        verdict=result.report.verdict,
    )

    # Read the episode before this check's own verdict lands, so `previous_verdict` is the
    # last verdict of an earlier check in the same firing episode.
    episode = await sync_to_async(episode_investigations, thread_sensitive=False)(alert, alert_check)

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
    await sync_to_async(_deliver_investigation_outcome, thread_sensitive=False)(
        alert=alert,
        alert_check=alert_check,
        verdict=result.report.verdict,
        previous_verdict=episode.previous_verdict,
        summary=summary_for_list or "",
        notebook_short_id=notebook.short_id,
        insight_chart_url=insight_chart_url,
    )

    # Surface the completed investigation to the Signals inbox, gated on the verdict so
    # false-positive fires don't become inbox noise (the verdict stays auditable on the
    # AlertCheck and in the notebook). Best-effort: the investigation itself has already
    # succeeded and been persisted, so a failure to emit must not fail the activity
    # (and trigger a re-run of the whole agent).
    if not should_emit_episode_signal(
        result.report.verdict, episode.previous_verdict, alert.investigation_inconclusive_action
    ):
        logger.info(
            "anomaly_investigation.signal_skipped",
            alert_id=str(alert.id),
            alert_check_id=str(alert_check.id),
            verdict=result.report.verdict,
        )
        return

    try:
        await _emit_investigation_signal(
            team=team,
            alert=alert,
            alert_check=alert_check,
            episode=episode,
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


def should_emit_investigation_signal(verdict: str | None, inconclusive_action: str | None) -> bool:
    """Whether a completed investigation should surface in the Signals inbox.

    True positives always emit; false positives never do. Inconclusive follows the
    alert's `investigation_inconclusive_action` policy, mirroring the notification
    gate, so one per-alert knob controls both surfaces.
    """
    if verdict == "true_positive":
        return True
    if verdict == "inconclusive":
        return (inconclusive_action or "notify") == "notify"
    return False


def should_emit_episode_signal(
    verdict: str | None, previous_verdict: str | None, inconclusive_action: str | None
) -> bool:
    """Whether this investigation should reach the Signals inbox.

    A re-investigation only emits when its verdict differs from the last one on the same
    episode. That bounds an incident to one emission per verdict it reaches, so a long
    incident cannot file a report for every check of it.
    """
    if verdict == previous_verdict:
        return False
    return should_emit_investigation_signal(verdict, inconclusive_action)


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
    episode: EpisodeInvestigations,
    insight: Insight,
    detector_type: str,
    report: InvestigationReport,
    notebook_short_id: str | None,
) -> None:
    """Emit an `alerts/anomaly_investigation` signal carrying the agent's verdict and findings.

    The source id is the episode's first check, not this one, so every investigation of one
    incident carries the same identity. Grouping matches a signal on its description and on
    semantically near signals, not on the source id, so one report per episode is a strong
    default and not a guarantee: a re-emit can still open a report of its own.
    """
    await signals.emit_signal(
        team=team,
        source_product=SIGNAL_SOURCE_PRODUCT,
        source_type=SIGNAL_SOURCE_TYPE,
        source_id=episode.first_check_id,
        description=_build_signal_description(
            alert_name=alert.name or "Unnamed alert",
            insight_name=insight.name or None,
            insight_id=str(insight.id),
            insight_short_id=getattr(insight, "short_id", None),
            report=report,
            previous_verdict=episode.previous_verdict,
        ),
        weight=1,
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
    previous_verdict: str | None = None,
) -> str:
    """Human-readable description embedded for grouping. Leads with the verdict, names the insight
    (with its id, handy for lookups), then the agent's summary, hypotheses, and recommendations.

    A re-investigation of the same episode leads with the verdict change instead, because that
    change is why the agent ran again."""
    verdict_label = report.verdict.replace("_", " ")
    metric = f" on {insight_name}" if insight_name else ""
    insight_ref = f"{insight_short_id} / id {insight_id}" if insight_short_id else f"id {insight_id}"
    headline = f"Anomaly investigation for alert '{alert_name}'{metric} (verdict: {verdict_label})."
    if previous_verdict and previous_verdict != report.verdict:
        headline = (
            f"Verdict changed from {previous_verdict.replace('_', ' ')} to {verdict_label} "
            f"for alert '{alert_name}'{metric}, which is still firing."
        )
    lines: list[str] = [
        headline,
        f"Insight: {insight_ref}.",
        report.summary,
    ]
    if report.metric_meaning.strip():
        # Grouping and triage both hinge on what the metric counts, which its name often misstates.
        lines.append(f"What the metric measures: {report.metric_meaning.strip()}")
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


def _inconclusive_is_suppressed(verdict: str | None, inconclusive_action: str | None) -> bool:
    """Whether an inconclusive verdict is held back by the alert's configured policy."""
    return verdict == "inconclusive" and (inconclusive_action or "notify") == "suppress"


def _should_suppress_notification(verdict: str | None, inconclusive_action: str | None) -> bool:
    """Whether the verdict holds the notification back: false positives always suppress,
    inconclusive follows the alert's configured policy."""
    return verdict == "false_positive" or _inconclusive_is_suppressed(verdict, inconclusive_action)


def _prepare_insight_chart_url(
    *,
    alert: AlertConfiguration,
    alert_check: AlertCheck,
    user: User,
    verdict: str | None,
) -> str | None:
    """Render the alerted insight to a PNG and mint a URL Slack can embed as an image block.

    Skipped when nothing would show it: a suppressed verdict, an already-delivered check
    (the common case for non-gated alerts, whose notification the main task sent
    synchronously), or no active Slack destination (only the Slack template renders the
    chart). Best-effort: on any failure (render error, no viewer access for the
    investigation user, export infrastructure down) return None so the notification still
    goes out, just without the chart.
    """
    if _should_suppress_notification(verdict, alert.investigation_inconclusive_action):
        return None
    pending = AlertCheck.objects.filter(
        id=alert_check.id, notification_sent_at__isnull=True, notification_suppressed_by_agent=False
    ).exists()
    if not pending:
        return None
    try:
        destinations = list_active_alert_destinations(
            team_id=alert.team_id, alert_id=str(alert.id), allowed_event_ids=(INSIGHT_ALERT_FIRING_EVENT,)
        )
        if not any(destination.destination_type == "slack" for destination in destinations):
            return None
        asset, content = exports.render_png_export(
            team=alert.team,
            created_by=user,
            insight_id=alert.insight_id,
            # System render: keep it out of the user's export listings and quota.
            is_system=True,
            expires_after=datetime.now(UTC) + _INSIGHT_CHART_ASSET_TTL,
        )
        if content is None:
            logger.info(
                "anomaly_investigation.insight_chart_render_failed",
                alert_id=str(alert.id),
                asset_id=asset.id,
                exception=asset.exception,
            )
            return None
        return exports.get_delivery_image_url(
            team_id=alert.team_id, asset_id=asset.id, expiry_delta=_INSIGHT_CHART_URL_TTL
        )
    except Exception:
        logger.exception("anomaly_investigation.insight_chart_render_failed", alert_id=str(alert.id))
        return None


def _deliver_investigation_outcome(
    *,
    alert,
    alert_check,
    verdict: str | None,
    previous_verdict: str | None,
    summary: str,
    notebook_short_id: str | None,
    insight_chart_url: str | None = None,
) -> None:
    """Decide what the user gets now that we have the verdict.

    For a check whose notification was held back (the episode's first fire):

    - true_positive → notify (enriched body with verdict + summary + notebook link)
    - false_positive → suppress, mark the check so the UI can surface why
    - inconclusive → fall back to the alert's configured policy
    - unknown / null verdict → notify (safest default)

    A later investigation of the same episode is not gated, so its notification already
    went out. It gets a follow-up only when the verdict changed, because the change is
    the news; an unchanged verdict would repeat what the user already read. A change to
    a false positive is a correction of a message the user already has, so it is sent
    rather than suppressed.

    Idempotent: if another codepath (retry, safety-net task) already dispatched,
    the first delivery is a no-op, and the follow-up is written once per check.
    """
    suppress = _should_suppress_notification(verdict, alert.investigation_inconclusive_action)

    with transaction.atomic():
        # Re-fetch under a row lock so concurrent dispatchers can't double-notify.
        check = AlertCheck.objects.select_for_update().get(id=alert_check.id)
        if check.notification_sent_at is not None or check.notification_suppressed_by_agent:
            _dispatch_verdict_change_followup(
                alert=alert,
                check=check,
                verdict=verdict,
                previous_verdict=previous_verdict,
                summary=summary,
                notebook_short_id=notebook_short_id,
            )
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
            alert_check=check,
            verdict=verdict,
            previous_verdict=previous_verdict,
            summary=summary,
            notebook_short_id=notebook_short_id,
        )
        # Event properties beyond the breach text, for HogFunction destinations. The notebook
        # URL backs the Slack "View Investigation" button (falls back to "View Alert" when
        # absent), and the chart URL renders as an image block of the alerted insight (the
        # block falls back to a divider when absent).
        extra_properties: dict[str, str] = {}
        if notebook_short_id:
            extra_properties["investigation_notebook_url"] = absolute_uri(f"/notebooks/{notebook_short_id}")
        if insight_chart_url:
            extra_properties["insight_chart_url"] = insight_chart_url
        try:
            deliveries = dispatch_alert_notification(alert, check, breaches, extra_properties=extra_properties or None)
            record_alert_delivery(alert, check, deliveries, stamp_on_empty=True)
        except Exception:
            logger.exception(
                "anomaly_investigation.gated_notification_failed",
                alert_id=str(alert.id),
                alert_check_id=str(alert_check.id),
            )
            # Don't swallow — let the safety-net task retry on the next tick.
            raise


def _dispatch_verdict_change_followup(
    *,
    alert,
    check,
    verdict: str | None,
    previous_verdict: str | None,
    summary: str,
    notebook_short_id: str | None,
) -> None:
    """Send one follow-up for a check whose notification already went out and whose verdict
    changed since the previous investigation of the same episode.

    A false positive does not hold this back the way it holds back a first notification.
    The user was already told the anomaly was real, so the correction is the whole point of
    the message. An inconclusive verdict still follows the alert's configured policy: a user
    who asked not to hear about unsure verdicts did not ask to hear about them here.

    Caller holds the row lock. The marker on `targets_notified` is the idempotency guard, so
    an activity retry past a successful send cannot notify twice. It is written only once a
    destination accepts the send, so a failed enqueue leaves the follow-up retryable.

    Never raises into the activity: a correction that cannot be sent is not worth a second
    agent run.
    """
    if not previous_verdict or verdict == previous_verdict:
        return
    if _inconclusive_is_suppressed(verdict, alert.investigation_inconclusive_action):
        return
    receipts = check.targets_notified or {}
    if receipts.get(_VERDICT_CHANGE_FOLLOWUP_KEY):
        return

    breaches = _build_breach_descriptions(
        alert_check=check,
        verdict=verdict,
        previous_verdict=previous_verdict,
        summary=summary,
        notebook_short_id=notebook_short_id,
    )
    extra_properties = (
        {"investigation_notebook_url": absolute_uri(f"/notebooks/{notebook_short_id}")} if notebook_short_id else None
    )
    try:
        # The savepoint keeps a database failure inside the dispatch from poisoning the
        # caller's transaction once the handler below swallows it.
        with transaction.atomic():
            # A key of its own: the check id already carries a delivery record per recipient
            # from the notification sent at fire time, and the email sender drops a second
            # send under the same campaign. Stable across retries, so at-most-once per
            # recipient still holds.
            deliveries = dispatch_alert_notification(
                alert,
                check,
                breaches,
                extra_properties=extra_properties,
                idempotency_key=f"{check.id}:investigation-verdict-change",
            )
    except Exception:
        # Best-effort, like the signal emit: the verdict is persisted and the user already
        # has the fire notification, so raising would rerun the whole agent for one
        # correction message. The safety net cannot recover this check either — it only
        # picks up checks that were never notified.
        logger.exception(
            "anomaly_investigation.verdict_change_followup_failed",
            alert_id=str(alert.id),
            alert_check_id=str(check.id),
        )
        return
    if not deliveries:
        # A failed enqueue and an alert with no destinations look the same from here, so
        # leave the marker unset. A later attempt can then send again, and an alert with no
        # destination has nothing to re-send. Marking it would lose the follow-up for good:
        # no sweep picks up a check whose notification already went out.
        logger.warning(
            "anomaly_investigation.verdict_change_followup_not_delivered",
            alert_id=str(alert.id),
            alert_check_id=str(check.id),
            verdict=verdict,
            previous_verdict=previous_verdict,
        )
        return
    check.targets_notified = {**receipts, _VERDICT_CHANGE_FOLLOWUP_KEY: True}
    check.save(update_fields=["targets_notified"])
    logger.info(
        "anomaly_investigation.verdict_change_followup_sent",
        alert_id=str(alert.id),
        alert_check_id=str(check.id),
        verdict=verdict,
        previous_verdict=previous_verdict,
    )


def _build_breach_descriptions(
    *,
    alert_check,
    verdict: str | None,
    previous_verdict: str | None,
    summary: str,
    notebook_short_id: str | None,
) -> list[str]:
    """Compose the strings that populate the `match_descriptions` list in the
    existing alert email template. Keeps the current template working while
    giving gated notifications richer body content.
    """
    lines: list[str] = []
    if previous_verdict and verdict and verdict != previous_verdict:
        lines.append(
            f"Investigation verdict changed from {_VERDICT_LABELS.get(previous_verdict, previous_verdict)} "
            f"to {_VERDICT_LABELS.get(verdict, verdict)} while this alert keeps firing."
        )
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

    verdict_label = _VERDICT_LABELS.get(verdict or "", "")
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

    window = trimmed[:MAX_SUMMARY_CHARS]
    # Prefer clipping at the last complete sentence, but only if it keeps enough of the
    # teaser — otherwise a short lead sentence would drop most of the summary.
    sentence_ends = [match.end() for match in _SENTENCE_END_RE.finditer(window)]
    if sentence_ends and sentence_ends[-1] >= MAX_SUMMARY_CHARS // 2:
        # Always append the ellipsis: the boundary might be an abbreviation (e.g. "U.S."),
        # not a real sentence end, so a clean-looking stop would hide that we dropped the rest.
        return window[: sentence_ends[-1]].rstrip() + " …"

    # No usable sentence boundary — fall back to the last word boundary with an ellipsis.
    word_end = window.rstrip().rfind(" ")
    if word_end != -1:
        return window[:word_end].rstrip() + "…"
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
