"""Hands a project's tickets to a Self-driving agent, and applies what the agent returns.

When a project escalates directly (`ai_gates.escalates_directly`), Support's own AI reply workflow
is off for it and the coordinator sends every settled ticket here. Self-driving calls back into
this module by dotted path (registered in `apps.py`): `load_ticket_for_agent` at the start of each
pass, `on_agent_run_result` once per pass, and `on_fix_run_ended` when a fix that a pass started ends.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.models import Team
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.utils import absolute_uri

from products.conversations.backend.events import capture_ticket_status_changed
from products.conversations.backend.facade.api import get_ticket_for_agent, post_ticket_internal_note
from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Status
from products.signals.backend.facade.agent_runs import (
    AgentEntity,
    AgentEntityContent,
    AgentRunOutcome,
    AgentRunRequestState,
    AgentRunResult,
    get_attached,
    request_agent_run,
)
from products.signals.backend.facade.api import ReportLinkSource, report_path

logger = structlog.get_logger(__name__)

AGENT = "research"
ENTITY_PRODUCT = "conversations"
ENTITY_TYPE = "ticket"
ESCALATION_COVERS_FIX_RUN_SETTING = "ai_escalation_covers_fix_run"
_ACTIVE_RUN_STATUSES = frozenset({"queued", "running"})


def ticket_entity(ticket_id: str) -> AgentEntity:
    return AgentEntity(product=ENTITY_PRODUCT, type=ENTITY_TYPE, id=str(ticket_id))


def load_ticket_for_agent(team_id: int, ticket_id: str) -> AgentEntityContent | None:
    ticket = get_ticket_for_agent(team_id, ticket_id)
    if ticket is None:
        return None
    return AgentEntityContent(
        title=ticket.subject,
        text="\n\n".join(f"{message.author_type}: {message.content}" for message in ticket.messages),
        url=ticket.url,
        content_hash=ticket.content_hash,
    )


def hand_ticket_to_self_driving(*, team_id: int, ticket_id: str) -> bool:
    """Ask Self-driving to look at the ticket. True when the request started a pass.

    Safe to repeat while the ticket stays eligible: a request for a ticket that the agent is reading,
    or has read as it is now, starts nothing.
    """
    # One transaction, so the pass starts only after the ticket shows that it is in progress. A pass
    # that fails at once then writes its result after this mark, not before it.
    with transaction.atomic():
        handle = request_agent_run(team_id=team_id, agent=AGENT, entity=ticket_entity(ticket_id), requested_by="triage")
        if handle.state == AgentRunRequestState.STARTED:
            _update_ticket(
                team_id,
                ticket_id,
                triage={"status": "in_progress", "run_id": handle.run_id, "started_at": timezone.now().isoformat()},
            )
    if handle.state == AgentRunRequestState.REJECTED:
        logger.info(
            "support_self_driving_request_rejected",
            team_id=team_id,
            ticket_id=ticket_id,
            reason_code=handle.reason_code,
        )
    return handle.state == AgentRunRequestState.STARTED


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _triage_result(result: AgentRunResult) -> str:
    """The existing triage result label that fits the pass, so the ticket list and AI panel can show it."""
    output = result.output or {}
    if result.outcome == AgentRunOutcome.BLOCKED:
        return "blocked_unsafe"
    if result.outcome == AgentRunOutcome.FAILED:
        return "escalated_no_reply"
    if result.outcome == AgentRunOutcome.NEEDS_INPUT:
        return "suggested_clarification"
    if result.outcome == AgentRunOutcome.REPORTS:
        return "escalated_with_findings"
    if output.get("ticket_type") == "unactionable":
        return "skipped_unactionable"
    return "suggested" if _text(output.get("suggested_reply")) else "escalated_with_findings"


def _string_list(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def triage_patch(result: AgentRunResult) -> dict[str, Any]:
    """What a pass writes into the ticket's `ai_triage`, in the shape the ticket page reads."""
    output = result.output or {}
    patch: dict[str, Any] = {
        "status": "done",
        "run_id": result.run_id,
        "finished_at": timezone.now().isoformat(),
        "result": _triage_result(result),
    }
    if result.outcome in (AgentRunOutcome.BLOCKED, AgentRunOutcome.FAILED):
        return patch
    return {
        **patch,
        "ticket_type": output.get("ticket_type"),
        # Set on every pass, so a verdict from an earlier pass does not outlive it.
        "verdict": "blocked_on_customer" if result.outcome == AgentRunOutcome.NEEDS_INPUT else None,
        "investigation_summary": _text(output.get("summary")),
        "unknowns": _string_list(output.get("unknowns")),
        "clarifying_questions": _string_list(output.get("clarifying_questions")),
        # The ticket page lists these as missing from knowledge. It is the only record of a gap topic.
        "missing": _string_list(output.get("knowledge_gap_topics")),
    }


def note_text(result: AgentRunResult) -> str | None:
    """The private note for a pass, or None when the agent wrote none.

    The agent writes the note for people who can read the ticket. Each linked report is added as a
    link and nothing more, because a ticket reader is not always allowed to read the report.
    """
    output = result.output or {}
    note = _text(output.get("private_note"))
    if not note:
        return None
    parts = [note]
    reply = _text(output.get("suggested_reply"))
    if reply:
        parts.append(f"**Suggested reply**\n\n{reply}")
    report_links = [
        f"Report: {absolute_uri(report_path(result.team_id, report.report_id, ReportLinkSource.SUPPORT))}"
        for report in result.reports
        if report.report_id not in note
    ]
    if report_links:
        parts.append("\n".join(report_links))
    return "\n\n".join(parts)


def _holds_for_fix_run(team: Team, result: AgentRunResult) -> bool:
    settings_dict = team.conversations_settings or {}
    return bool(settings_dict.get(ESCALATION_COVERS_FIX_RUN_SETTING)) and any(
        report.implementation.run_active for report in result.reports
    )


def _announce_reopened(ticket: Ticket, old_status: str) -> None:
    """Tell workflows and the activity log that the system moved the ticket back to open."""
    try:
        capture_ticket_status_changed(ticket, old_status, Status.OPEN, actor_type="system")
    except Exception:
        logger.exception("support_self_driving_status_event_failed", ticket_id=str(ticket.id))
    try:
        log_activity(
            organization_id=ticket.team.organization_id,
            team_id=ticket.team_id,
            user=None,
            was_impersonated=False,
            item_id=str(ticket.id),
            scope="Ticket",
            activity="updated",
            detail=Detail(
                name=f"Ticket #{ticket.ticket_number}",
                changes=[Change(type="Ticket", field="status", before=old_status, after=Status.OPEN, action="changed")],
            ),
        )
    except Exception:
        logger.exception("support_self_driving_activity_log_failed", ticket_id=str(ticket.id))


def _update_ticket(team_id: int, ticket_id: str, *, triage: dict[str, Any] | None = None, reopen: bool = False) -> None:
    """Merge `triage` into the ticket's AI triage and, when `reopen`, set an escalated ticket back to open.

    Only an escalated ticket is reopened, so a status that a teammate set during the run is left as it is.
    """
    with transaction.atomic():
        ticket = (
            Ticket.objects.select_for_update(of=("self",))
            .select_related("team")
            .filter(team_id=team_id, id=ticket_id)
            .first()
        )
        if ticket is None:
            return
        update_fields = ["updated_at"]
        if triage is not None:
            current = ticket.ai_triage if isinstance(ticket.ai_triage, dict) else {}
            ticket.ai_triage = {"schema_version": 1, **current, **triage}
            update_fields.append("ai_triage")
        old_status = ticket.status
        reopened = reopen and old_status == Status.ESCALATED
        if reopened:
            ticket.status = Status.OPEN
            update_fields.append("status")
        ticket.save(update_fields=update_fields)
    if reopened:
        _announce_reopened(ticket, old_status)


def on_agent_run_result(result: AgentRunResult) -> None:
    """Apply one pass's result to its ticket. Safe to call again for the same pass."""
    team_id, ticket_id = result.team_id, result.entity.id
    note = note_text(result)
    if note is not None:
        post_ticket_internal_note(team_id, ticket_id, note, dedupe_key=f"self_driving_agent_run:{result.run_id}")
    team = Team.objects.filter(id=team_id).first()
    if team is None:
        return
    triage = triage_patch(result)
    if result.next_pass_queued:
        # One more pass waits to start, so the agent is not done with the ticket.
        _update_ticket(team_id, ticket_id, triage={**triage, "status": "in_progress"})
    else:
        _update_ticket(team_id, ticket_id, triage=triage, reopen=not _holds_for_fix_run(team, result))


def on_fix_run_ended(team_id: int, entity: AgentEntity, report_id: str) -> None:
    """Set an escalated ticket back to open when the fix run for one of its reports ended.

    The ticket stays as it is while the agent still reads it, or while another fix run for it is running.
    """
    attached = get_attached(team_id=team_id, product=entity.product, type=entity.type, ids=[entity.id]).get(entity.id)
    if attached is None:
        return
    if attached.run is not None and attached.run.status in _ACTIVE_RUN_STATUSES:
        return
    if any(report.implementation.run_active for report in attached.reports):
        return
    logger.info("support_self_driving_fix_run_ended", team_id=team_id, ticket_id=entity.id, report_id=report_id)
    _update_ticket(team_id, entity.id, reopen=True)
