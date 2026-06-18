from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    from django.utils import timezone

    import structlog
    import posthoganalytics

    from posthog.models.comment import Comment
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.heartbeat import Heartbeater

    from products.business_knowledge.backend.logic import has_ready_sources
    from products.conversations.backend.models import Ticket
    from products.conversations.backend.temporal.pipeline import SupportReplyInput, SupportReplyWorkflow

logger = structlog.get_logger(__name__)

COORDINATOR_INTERVAL_MINUTES = 5
TICKET_LOOKBACK_MINUTES = 6

MASTER_FLAG = "product-support-ai-suggestion"
ROLLOUT_FLAG = "product-support-ai-suggestion-rollout"


@dataclass
class CoordinatorInput:
    pass


@dataclass
class CoordinatorOutput:
    eligible_count: int
    started_count: int
    skipped_count: int


@dataclass
class EligibleTicket:
    team_id: int
    ticket_id: str


@dataclass
class CollectEligibleTicketsOutput:
    tickets: list[EligibleTicket]


def _is_master_flag_enabled(team_id: int) -> bool:
    return bool(
        posthoganalytics.feature_enabled(
            MASTER_FLAG,
            str(team_id),
        )
    )


def _is_rollout_enabled(ticket_id: str) -> bool:
    return bool(
        posthoganalytics.feature_enabled(
            ROLLOUT_FLAG,
            ticket_id,
        )
    )


def _collect_eligible(lookback_minutes: int = TICKET_LOOKBACK_MINUTES) -> list[EligibleTicket]:
    """Sync DB scan for eligible tickets. Runs in a worker thread."""
    cutoff = timezone.now() - timedelta(minutes=lookback_minutes)
    recent_tickets = Ticket.objects.filter(created_at__gte=cutoff).select_related("team__organization")
    eligible: list[EligibleTicket] = []

    for ticket in recent_tickets:
        team = ticket.team
        ticket_id_str = str(ticket.id)

        if not _is_master_flag_enabled(team.id):
            continue

        settings_dict = team.conversations_settings or {}
        if not settings_dict.get("ai_suggestions_enabled", False):
            continue

        if not team.organization.is_ai_data_processing_approved:
            continue

        if not has_ready_sources(team.id):
            continue

        # Dedupe: skip if there's already an AI note or a team reply
        has_ai_note = Comment.objects.filter(
            team_id=team.id,
            scope="conversations_ticket",
            item_id=ticket_id_str,
            item_context__author_type="AI",
        ).exists()
        if has_ai_note:
            continue

        has_team_reply = (
            Comment.objects.filter(
                team_id=team.id,
                scope="conversations_ticket",
                item_id=ticket_id_str,
            )
            .exclude(
                item_context__author_type="customer",
            )
            .exclude(
                item_context__author_type="AI",
            )
            .filter(
                item_context__author_type__in=["support", "team"],
            )
            .exists()
        )
        if has_team_reply:
            continue

        if not _is_rollout_enabled(ticket_id_str):
            continue

        eligible.append(EligibleTicket(team_id=team.id, ticket_id=ticket_id_str))

    return eligible


@activity.defn
async def collect_eligible_tickets_activity(_input: CoordinatorInput) -> CollectEligibleTicketsOutput:
    """Scan for recent tickets and gate them through all eligibility checks."""
    async with Heartbeater():
        tickets = await database_sync_to_async(_collect_eligible, thread_sensitive=False)()
    logger.info("support_reply coordinator: eligible tickets", count=len(tickets))
    return CollectEligibleTicketsOutput(tickets=tickets)


@workflow.defn(name="support-reply-coordinator")
class SupportReplyCoordinatorWorkflow:
    """Coordinator: polls for new tickets, gates them, fans out child reply workflows.

    Dispatch is fire-and-forget via ParentClosePolicy.ABANDON. Child workflow IDs
    are deterministic per (ticket_id, tick_id) so retries/replays are idempotent.
    ScheduleOverlapPolicy.SKIP prevents concurrent ticks.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> CoordinatorInput:
        if not inputs:
            return CoordinatorInput()
        loaded = json.loads(inputs[0])
        return CoordinatorInput(**loaded)

    @workflow.run
    async def run(self, _input: CoordinatorInput) -> CoordinatorOutput:
        result = await workflow.execute_activity(
            collect_eligible_tickets_activity,
            _input,
            start_to_close_timeout=timedelta(minutes=3),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        tickets = result.tickets
        if not tickets:
            return CoordinatorOutput(eligible_count=0, started_count=0, skipped_count=0)

        tick_id = workflow.info().workflow_id
        started = 0
        skipped = 0

        for idx, ticket in enumerate(tickets):
            child_id = f"support-reply-{ticket.ticket_id}-{tick_id}-{idx}"
            try:
                await workflow.start_child_workflow(
                    SupportReplyWorkflow.run,
                    SupportReplyInput(team_id=ticket.team_id, ticket_id=ticket.ticket_id),
                    id=child_id,
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                    parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                )
                started += 1
            except WorkflowAlreadyStartedError:
                workflow.logger.info(
                    "support_reply coordinator: child already running",
                    ticket_id=ticket.ticket_id,
                    child_id=child_id,
                )
                skipped += 1

        return CoordinatorOutput(
            eligible_count=len(tickets),
            started_count=started,
            skipped_count=skipped,
        )
