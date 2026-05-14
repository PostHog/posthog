"""Temporal activities for the live investigation primitive."""

from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from django.utils import timezone

from temporalio import activity

from posthog.models import User
from posthog.temporal.ai.live_investigation.runner import run_followup_investigation
from posthog.temporal.ai.live_investigation.schemas import (
    AnalyzeInput,
    LiveInvestigationFindings,
    MarkCancelledInput,
    UninstallInput,
)
from posthog.temporal.common.heartbeat import Heartbeater

from products.live_debugger.backend.models import LiveDebuggerProgram, LiveInvestigation

logger = logging.getLogger(__name__)


def _pick_billing_user(team_id: int) -> User | None:
    """Pick any org member as the LLM-call billing attribution.

    Live investigations don't have a natural "owning user" (signal sources are
    automated). We need a real User to satisfy MaxChatAnthropic's billing/context
    injection requirement; any org member with access to this team will do.
    """
    return User.objects.filter(organization_memberships__organization__teams__id=team_id).first()


def _gave_up_findings(reason: str) -> LiveInvestigationFindings:
    return LiveInvestigationFindings(
        status="gave_up",
        summary=reason[:500],
        confidence=0.0,
        hypothesis_outcome="inconclusive",
    )


@activity.defn
async def analyze_live_investigation_activity(input: AnalyzeInput) -> None:
    """Load brief + events, run the followup agent, persist findings.

    Best-effort: any failure produces a `gave_up` findings record so the row
    always reaches a terminal state.
    """
    investigation: LiveInvestigation = await LiveInvestigation.objects.select_related(
        "team", "program", "parent"
    ).aget(id=input.investigation_id)

    # Idempotency: if analysis already ran (e.g. retry after a partial success),
    # don't re-run the LLM call.
    if investigation.status in (LiveInvestigation.Status.COMPLETE, LiveInvestigation.Status.CANCELLED):
        logger.info(
            "live_investigation.analyze_skipped_terminal_status",
            extra={"investigation_id": str(investigation.id), "status": investigation.status},
        )
        return

    investigation.status = LiveInvestigation.Status.ANALYZING
    await investigation.asave(update_fields=["status"])

    try:
        async with Heartbeater():
            user = await sync_to_async(_pick_billing_user, thread_sensitive=False)(investigation.team_id)
            if user is None:
                findings = _gave_up_findings(
                    f"No user available to bill the followup agent for team {investigation.team_id}"
                )
            else:
                events = await sync_to_async(
                    LiveDebuggerProgram.get_program_events, thread_sensitive=False
                )(
                    team=investigation.team,
                    program_id=str(investigation.program_id),
                    limit=100,
                )
                findings = await run_followup_investigation(
                    investigation=investigation,
                    events=events,
                    user=user,
                    heartbeat=activity.heartbeat,
                )
    except Exception as err:
        logger.exception("live_investigation.analyze_failed", extra={"investigation_id": str(investigation.id)})
        findings = _gave_up_findings(f"Analysis activity raised: {err}")

    investigation.findings = findings.model_dump(mode="json")
    investigation.status = LiveInvestigation.Status.COMPLETE
    investigation.completed_at = timezone.now()
    await investigation.asave(update_fields=["findings", "status", "completed_at"])


@activity.defn
async def uninstall_program_activity(input: UninstallInput) -> None:
    """Soft-uninstall the program. Idempotent."""
    await LiveDebuggerProgram.objects.filter(id=input.program_id).aupdate(
        status=LiveDebuggerProgram.Status.UNINSTALLED,
    )


@activity.defn
async def mark_investigation_cancelled_activity(input: MarkCancelledInput) -> None:
    """Flip status to CANCELLED. Used when the close signal fires before analysis."""
    await LiveInvestigation.objects.filter(id=input.investigation_id).aupdate(
        status=LiveInvestigation.Status.CANCELLED,
        completed_at=timezone.now(),
    )
