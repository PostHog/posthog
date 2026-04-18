"""Temporal workflow that kicks off the anomaly investigation agent and persists
its findings as a Notebook linked to the AlertCheck.

Triggered from posthog/tasks/alerts/checks.py when an alert transitions to FIRING.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional
from uuid import UUID

from asgiref.sync import sync_to_async
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.models import Team, User

logger = logging.getLogger(__name__)


ANOMALY_INVESTIGATION_ACTIVITY_START_TO_CLOSE = 20 * 60  # 20 minutes
ANOMALY_INVESTIGATION_ACTIVITY_HEARTBEAT_TIMEOUT = 5 * 60  # 5 minutes
ANOMALY_INVESTIGATION_ACTIVITY_MAX_ATTEMPTS = 2


@dataclass
class AnomalyInvestigationWorkflowInputs:
    team_id: int
    alert_id: UUID
    alert_check_id: UUID
    user_id: Optional[int] = None
    trace_id: Optional[str] = None


@workflow.defn(name="anomaly-investigation")
class AnomalyInvestigationWorkflow:
    """Single-activity workflow — the heavy lifting happens inside the activity."""

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
    # Imports happen inside the activity because Temporal's workflow sandbox restricts
    # what modules the workflow class itself can import at definition time.
    from posthog.models.alert import AlertCheck, AlertConfiguration, InvestigationStatus
    from posthog.temporal.ai.anomaly_investigation.notebook import NotebookRenderContext, build_investigation_notebook
    from posthog.temporal.ai.anomaly_investigation.prompts import build_anomaly_context
    from posthog.temporal.ai.anomaly_investigation.runner import run_investigation
    from posthog.temporal.common.heartbeat import Heartbeater

    from products.notebooks.backend.models import Notebook

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

    anomaly_context = build_anomaly_context(
        alert_name=alert.name or "Unnamed alert",
        metric_description=metric_description,
        detector_type=detector_type,
        triggered_dates=list(alert_check.triggered_dates or []),
        triggered_metadata=alert_check.triggered_metadata,
        calculated_value=alert_check.calculated_value,
        interval=alert_check.interval,
    )

    try:
        async with Heartbeater():
            result = await run_investigation(
                team=team,
                user=user,
                anomaly_context=anomaly_context,
                heartbeat=activity.heartbeat,
            )
    except Exception as err:
        logger.exception("anomaly_investigation.agent_failed", extra={"alert_id": str(alert.id)})
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

    notebook = await sync_to_async(Notebook.objects.create, thread_sensitive=False)(
        team=team,
        title=f"Investigation — {alert.name or 'anomaly alert'}",
        content=notebook_content,
        text_content=result.report.summary,
        created_by=user,
        last_modified_by=user,
        visibility=Notebook.Visibility.DEFAULT,
    )

    await sync_to_async(AlertCheck.objects.filter(id=alert_check.id).update, thread_sensitive=False)(
        investigation_notebook_id=notebook.id,
        investigation_status=InvestigationStatus.DONE,
        investigation_verdict=result.report.verdict,
        investigation_summary=_truncate_summary(result.report.summary),
        investigation_error=None,
    )


MAX_SUMMARY_CHARS = 500


def _truncate_summary(summary: str | None) -> str | None:
    """Clamp the agent's summary for list rendering and email/Slack follow-ups.

    The full write-up already lives in the notebook — this field is just a teaser.
    """
    if not summary:
        return None
    trimmed = summary.strip()
    if len(trimmed) <= MAX_SUMMARY_CHARS:
        return trimmed
    return trimmed[: MAX_SUMMARY_CHARS - 1].rstrip() + "…"


async def _update_status(alert_check, status: str) -> None:
    from posthog.models.alert import AlertCheck

    await sync_to_async(AlertCheck.objects.filter(id=alert_check.id).update, thread_sensitive=False)(
        investigation_status=status,
    )


async def _mark_failed(alert_check, reason: str) -> None:
    from posthog.models.alert import AlertCheck, InvestigationStatus

    await sync_to_async(AlertCheck.objects.filter(id=alert_check.id).update, thread_sensitive=False)(
        investigation_status=InvestigationStatus.FAILED,
        investigation_error={"message": reason},
    )


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
