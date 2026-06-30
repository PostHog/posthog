from __future__ import annotations

from django.conf import settings
from django.db import transaction

import structlog
from temporalio import activity

from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.utils import close_db_connections

from products.conversations.backend.models import Ticket
from products.conversations.backend.temporal.ai_reply.schemas import DispatchBugFixInput, DispatchBugFixOutput
from products.conversations.backend.temporal.helpers import resolve_user_id_for_support
from products.tasks.backend.facade import api as tasks_facade

logger = structlog.get_logger(__name__)


def _build_bug_fix_task_description(*, team_id: int, ticket_id: str, summary: str, repository: str) -> str:
    ticket_url = f"{settings.SITE_URL}/project/{team_id}/support/tickets/{ticket_id}"
    return (
        f"{summary}\n\n"
        f"Repository: {repository}\n\n"
        "Address the symptom described above — not merely an adjacent issue you notice nearby. "
        "Investigate the root cause, implement the fix, and open a PR if appropriate. "
        "If your change fixes something related but does not change what the user actually observed, "
        "say so explicitly and stop rather than opening a PR for the wrong problem.\n\n"
        f"When opening the PR, include this support ticket link in the description footer: {ticket_url}"
    )


@activity.defn(name="support-dispatch-bug-fix")
@close_db_connections
async def support_dispatch_bug_fix_activity(input: DispatchBugFixInput) -> DispatchBugFixOutput:
    """Create a Tasks implementation run to fix a reported bug and open a draft PR."""
    return await database_sync_to_async(_dispatch_bug_fix_sync, thread_sensitive=False)(
        input.team_id,
        input.ticket_id,
        input.repository,
        input.title,
        input.summary,
    )


def _dispatch_bug_fix_sync(
    team_id: int,
    ticket_id: str,
    repository: str,
    title: str,
    summary: str,
) -> DispatchBugFixOutput:
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().filter(team_id=team_id, id=ticket_id).first()
        if ticket is None:
            return DispatchBugFixOutput(dispatched=False, skipped_reason="ticket_not_found")

        triage = ticket.ai_triage or {}
        if triage.get("bug_fix_task_id"):
            return DispatchBugFixOutput(
                dispatched=False,
                skipped_reason="already_dispatched",
                task_id=str(triage["bug_fix_task_id"]),
            )

        team = Team.objects.select_related("organization").get(id=team_id)
        user_id = resolve_user_id_for_support(team_id)
        description = _build_bug_fix_task_description(
            team_id=team_id,
            ticket_id=ticket_id,
            summary=summary,
            repository=repository,
        )

        created = tasks_facade.create_and_run_task(
            team=team,
            title=title,
            description=description,
            origin_product=tasks_facade.TaskOriginProduct.SUPPORT_REPLY,
            user_id=user_id,
            repository=repository,
            create_pr=True,
            interaction_origin="support_reply",
            # Ticket content is attacker-controlled (public widget/email). Keep the coding agent's
            # PostHog MCP access read-only so a prompt-injected fix run can't write/exfiltrate
            # project data — it only needs the repo (via the GitHub integration) plus read context.
            posthog_mcp_scopes="read_only",
        )
        if created.latest_run is None:
            raise RuntimeError(f"Bug-fix task {created.task_id} auto-started without producing a TaskRun")

        task_id = str(created.task_id)
        run_id = str(created.latest_run.id)
        ticket.ai_triage = {
            **triage,
            "bug_fix_dispatched": True,
            "bug_fix_task_id": task_id,
            "bug_fix_run_id": run_id,
        }
        ticket.save(update_fields=["ai_triage", "updated_at"])

        logger.info(
            "support_reply_bug_fix_dispatched",
            team_id=team_id,
            ticket_id=ticket_id,
            task_id=task_id,
            run_id=run_id,
            repository=repository,
        )
        return DispatchBugFixOutput(dispatched=True, task_id=task_id, run_id=run_id)
