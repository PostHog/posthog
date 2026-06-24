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

COORDINATOR_INTERVAL_MINUTES = 1
TICKET_LOOKBACK_MINUTES = 2

# Fanout caps so public ticket volume can't directly turn into unbounded sandbox/LLM work.
# A single opted-in team that gets flooded with externally-created tickets can only spend
# MAX_TICKETS_PER_TEAM_PER_RUN drafts per tick; the global cap bounds total work across teams.
# Anything over the cap simply rolls to the next tick (the lookback window keeps it eligible).
MAX_TICKETS_PER_TEAM_PER_RUN = 10
MAX_TICKETS_PER_RUN = 50

MASTER_FLAG = "product-support-ai-suggestion"
ROLLOUT_FLAG = "product-support-ai-suggestion-rollout"

# Minimum number of READY BK sources required before the coordinator will draft replies.
# Set to 0 locally to skip the BK readiness check entirely.
MIN_READY_BK_SOURCES = 0


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

    # First pass: the cheap per-ticket gates that don't touch the comments table.
    candidates: list[tuple[int, str]] = []
    for ticket in recent_tickets:
        team = ticket.team

        if not _is_master_flag_enabled(team.id):
            continue

        settings_dict = team.conversations_settings or {}
        if not settings_dict.get("ai_suggestions_enabled", False):
            continue

        if not team.organization.is_ai_data_processing_approved:
            continue

        if MIN_READY_BK_SOURCES > 0 and not has_ready_sources(team.id):
            continue

        candidates.append((team.id, str(ticket.id)))

    if not candidates:
        return []

    # Dedupe in one query per team instead of two `.exists()` round-trips per ticket. A ticket
    # is "already engaged" iff it has any comment that isn't from the customer: our own AI note
    # ("AI") or a human/team reply ("support"/"team", or "human" from the compose flow). Keying
    # the query on (team_id, scope, item_id) keeps it on the matching index.
    by_team: dict[int, list[str]] = {}
    for team_id, ticket_id_str in candidates:
        by_team.setdefault(team_id, []).append(ticket_id_str)

    engaged: set[str] = set()
    for team_id, ticket_ids in by_team.items():
        for item_id, author_type in Comment.objects.filter(
            team_id=team_id,
            scope="conversations_ticket",
            item_id__in=ticket_ids,
        ).values_list("item_id", "item_context__author_type"):
            if author_type != "customer":
                engaged.add(item_id)

    # Rollout is sampled last (after the cheap gates and dedupe) so we don't burn the bucket on
    # tickets that were never going to run. Per-team and global caps bound how many child
    # workflows a single tick can fan out so externally-created ticket volume can't directly
    # translate into unbounded LLM work; overflow rolls to the next tick (still in lookback).
    eligible: list[EligibleTicket] = []
    per_team_counts: dict[int, int] = {}
    for team_id, ticket_id_str in candidates:
        if len(eligible) >= MAX_TICKETS_PER_RUN:
            break
        if ticket_id_str in engaged:
            continue
        if per_team_counts.get(team_id, 0) >= MAX_TICKETS_PER_TEAM_PER_RUN:
            continue
        if not _is_rollout_enabled(ticket_id_str):
            continue
        per_team_counts[team_id] = per_team_counts.get(team_id, 0) + 1
        eligible.append(EligibleTicket(team_id=team_id, ticket_id=ticket_id_str))

    return eligible


@activity.defn
async def support_collect_eligible_tickets_activity(_input: CoordinatorInput) -> CollectEligibleTicketsOutput:
    """Scan for recent tickets and gate them through all eligibility checks."""
    async with Heartbeater():
        tickets = await database_sync_to_async(_collect_eligible, thread_sensitive=False)()
    logger.info("support_reply coordinator: eligible tickets", count=len(tickets))
    return CollectEligibleTicketsOutput(tickets=tickets)


@workflow.defn(name="support-reply-coordinator")
class SupportReplyCoordinatorWorkflow:
    """Coordinator: polls for new tickets, gates them, fans out child reply workflows.

    Dispatch is fire-and-forget via ParentClosePolicy.ABANDON. Child workflow IDs are
    deterministic per ticket (`support-reply-<ticket_id>`), so the same ticket can't be drafted
    twice while a run is in flight (the lookback window of 6m intentionally overlaps the 5m
    schedule interval): a running child conflicts on its id before its AI note lands and the DB
    dedupe can see it. ALLOW_DUPLICATE_FAILED_ONLY still lets a later tick retry a ticket whose
    prior pipeline run failed. ScheduleOverlapPolicy.SKIP only guards against a slow tick
    overlapping the next one.
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
            support_collect_eligible_tickets_activity,
            _input,
            start_to_close_timeout=timedelta(minutes=3),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        tickets = result.tickets
        if not tickets:
            return CoordinatorOutput(eligible_count=0, started_count=0, skipped_count=0)

        started = 0
        skipped = 0

        for ticket in tickets:
            # Keyed on ticket id only (not the tick id) so the id guard dedupes the same ticket
            # across overlapping ticks, not just within a single coordinator run. A still-running
            # child always conflicts on its id regardless of reuse policy; ALLOW_DUPLICATE_FAILED_ONLY
            # additionally lets a tick re-dispatch a ticket whose prior pipeline run *failed* (which
            # leaves no AI note for the DB dedupe to catch), while a succeeded/escalated run stays
            # de-duped — the success case also leaves an AI note that the DB gate catches first.
            child_id = f"support-reply-{ticket.ticket_id}"
            try:
                await workflow.start_child_workflow(
                    SupportReplyWorkflow.run,
                    SupportReplyInput(team_id=ticket.team_id, ticket_id=ticket.ticket_id),
                    id=child_id,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
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
