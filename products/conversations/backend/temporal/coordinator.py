from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

if TYPE_CHECKING:
    from posthog.models import Team

with workflow.unsafe.imports_passed_through():
    from django.db.models import Q
    from django.utils import timezone

    import structlog
    import posthoganalytics

    from posthog.models.comment import Comment
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.heartbeat import Heartbeater

    from products.business_knowledge.backend.logic import has_ready_sources
    from products.conversations.backend.models import Ticket
    from products.conversations.backend.models.constants import Status
    from products.conversations.backend.temporal.pipeline import SupportReplyInput, SupportReplyWorkflow

logger = structlog.get_logger(__name__)

COORDINATOR_INTERVAL_MINUTES = 1

# Settle/debounce window: don't draft until the customer has been quiet (no new message) for this
# long. Lets someone raise a ticket and immediately fire off 1-2 follow-ups without the AI drafting
# off only the first message. The reference is max(ticket.created_at, latest customer comment), so a
# brand-new ticket also waits this long before its first draft — the latency we trade for completeness.
TICKET_SETTLE_MINUTES = 1

# Scan window. Keyed on last_message_at (the same axis the settle gate uses), so a ticket stays
# eligible until SETTLE after its *last* customer message, regardless of how long ago it was created
# — a late follow-up can't push the settle deadline past the scan window and silently drop the
# ticket. Only needs to exceed SETTLE + interval + a little slack for a slow tick.
TICKET_LOOKBACK_MINUTES = 5

# Fanout caps so public ticket volume can't directly turn into unbounded sandbox/LLM work.
# A single opted-in team that gets flooded with externally-created tickets can only spend
# MAX_TICKETS_PER_TEAM_PER_RUN drafts per tick; the global cap bounds total work across teams.
# Anything over the cap simply rolls to the next tick (the lookback window keeps it eligible).
MAX_TICKETS_PER_TEAM_PER_RUN = 10
MAX_TICKETS_PER_RUN = 50

MASTER_FLAG = "product-support-ai-suggestion"

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


def _is_master_flag_enabled(team: Team) -> bool:
    # The flag is targeted by project group; release conditions can match on the project's `uuid`,
    # so it must be in group_properties — the headless worker only sends what's listed here (unlike
    # posthog-js, which auto-attaches full group properties). Without it a uuid filter never matches.
    try:
        return bool(
            posthoganalytics.feature_enabled(
                MASTER_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id), "uuid": str(team.uuid)},
                },
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        # A flag-service blip must skip the ticket, not throw inside the scan loop and fail the
        # whole coordinator tick. Fail closed: treat as disabled.
        logger.warning("support_reply coordinator: master flag eval failed", team_id=team.id, exc_info=True)
        return False


def _collect_eligible(lookback_minutes: int = TICKET_LOOKBACK_MINUTES) -> list[EligibleTicket]:
    """Sync DB scan for eligible tickets. Runs in a worker thread."""
    now = timezone.now()
    cutoff = now - timedelta(minutes=lookback_minutes)
    # last_message_at is the debounce axis; fall back to created_at for tickets whose denormalized
    # timestamp hasn't landed yet (set via a post-commit signal, so there's a brief null window).
    recent_tickets = Ticket.objects.filter(
        Q(last_message_at__gte=cutoff) | Q(last_message_at__isnull=True, created_at__gte=cutoff),
        status__in=[Status.NEW, Status.OPEN],
    ).select_related("team__organization")

    # First pass: the cheap per-ticket gates that don't touch the comments table. We keep
    # created_at around so a ticket with no customer comments yet still settles from its own
    # creation time (the initial message), not just from follow-up comments.
    candidates: list[tuple[int, str, datetime]] = []
    for ticket in recent_tickets:
        team = ticket.team

        if not _is_master_flag_enabled(team):
            continue

        settings_dict = team.conversations_settings or {}
        if not settings_dict.get("ai_suggestions_enabled", False):
            continue

        allowed_channels = settings_dict.get("ai_resolution_channels")
        if allowed_channels is not None and ticket.channel_source not in allowed_channels:
            continue

        if not team.organization.is_ai_data_processing_approved:
            continue

        if MIN_READY_BK_SOURCES > 0 and not has_ready_sources(team.id):
            continue

        candidates.append((team.id, str(ticket.id), ticket.created_at))

    if not candidates:
        return []

    # One comment query per team instead of round-trips per ticket. Two things come out of it:
    #   1. Dedupe: a ticket is "already engaged" iff it has any non-customer comment — our own AI
    #      note ("AI") or a human/team reply ("support"/"team"/"human"). Those are excluded below.
    #   2. Settle/debounce: the latest customer comment timestamp per ticket. Since engaged tickets
    #      are dropped anyway, for everything we actually consider the latest customer comment is
    #      simply the latest message on the ticket. Keying on (team_id, scope, item_id) hits the index.
    by_team: dict[int, list[str]] = {}
    for team_id, ticket_id_str, _created_at in candidates:
        by_team.setdefault(team_id, []).append(ticket_id_str)

    engaged: set[str] = set()
    latest_customer_msg: dict[str, datetime] = {}
    for team_id, ticket_ids in by_team.items():
        for item_id, author_type, comment_created_at in Comment.objects.filter(
            team_id=team_id,
            scope="conversations_ticket",
            item_id__in=ticket_ids,
        ).values_list("item_id", "item_context__author_type", "created_at"):
            if author_type != "customer":
                engaged.add(item_id)
                continue
            prev = latest_customer_msg.get(item_id)
            if prev is None or comment_created_at > prev:
                latest_customer_msg[item_id] = comment_created_at

    # Per-team and global caps bound how many child workflows a single tick can fan out so
    # externally-created ticket volume can't directly translate into unbounded LLM work; overflow
    # rolls to the next tick (still in lookback).
    settle_cutoff = now - timedelta(minutes=TICKET_SETTLE_MINUTES)
    eligible: list[EligibleTicket] = []
    per_team_counts: dict[int, int] = {}
    for team_id, ticket_id_str, created_at in candidates:
        if len(eligible) >= MAX_TICKETS_PER_RUN:
            break
        if ticket_id_str in engaged:
            continue
        # Settle: wait until the customer has gone quiet. Reference is the most recent customer
        # activity — max(ticket creation, latest customer comment). If that's newer than the
        # cutoff the ticket is still settling; skip it and let a later tick pick it up.
        last_activity = max(created_at, latest_customer_msg.get(ticket_id_str, created_at))
        if last_activity > settle_cutoff:
            continue
        if per_team_counts.get(team_id, 0) >= MAX_TICKETS_PER_TEAM_PER_RUN:
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
    twice while a run is in flight (the lookback window intentionally overlaps the schedule
    interval): a running child conflicts on its id before its AI note lands and the DB dedupe can
    see it. ALLOW_DUPLICATE_FAILED_ONLY still lets a later tick retry a ticket whose prior pipeline
    run failed. ScheduleOverlapPolicy.SKIP only guards against a slow tick overlapping the next one.
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
