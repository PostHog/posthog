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

    from posthog.models import Team
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.heartbeat import Heartbeater

    from products.conversations.backend.models import IncidentStatus, Ticket, TicketIncident
    from products.conversations.backend.temporal.trends.workflow import (
        TicketTrendsAnalysisWorkflow,
        TrendsAnalysisInput,
    )

logger = structlog.get_logger(__name__)

TRENDS_COORDINATOR_INTERVAL_MINUTES = 15

# Lookback for "team has new tickets": 2× the interval plus slack, so a tick
# skipped by ScheduleOverlapPolicy.SKIP can't silently drop a team.
TEAM_LOOKBACK_MINUTES = 35

# Bounds coordinator fan-out; overflow teams roll to the next tick (a missed
# evaluation delays an alert by one interval, it doesn't lose it).
MAX_TEAMS_PER_RUN = 200

MASTER_FLAG = "support-ticket-trends"


@dataclass
class TrendsCoordinatorInput:
    pass


@dataclass
class TrendsCoordinatorOutput:
    eligible_count: int
    started_count: int
    skipped_count: int


@dataclass
class CollectEligibleTeamsOutput:
    team_ids: list[int]


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
        # A flag-service blip must skip the team, not fail the whole coordinator tick.
        # Fail closed: treat as disabled.
        logger.warning("ticket_trends coordinator: master flag eval failed", team_id=team.id, exc_info=True)
        return False


def _collect_eligible_teams() -> list[int]:
    """Teams worth analyzing this tick: new tickets recently (a spike needs new
    tickets) or an open incident (auto-resolve must progress even when traffic
    stops). Idle teams cost nothing beyond these two indexed scans."""
    now = timezone.now()
    cutoff = now - timedelta(minutes=TEAM_LOOKBACK_MINUTES)

    recent_team_ids = set(Ticket.objects.filter(created_at__gte=cutoff).values_list("team_id", flat=True).distinct())
    # Cross-team scan is the coordinator's job; per-team access happens in the child workflow.
    open_incident_team_ids = set(
        TicketIncident.objects.unscoped()
        .filter(status=IncidentStatus.ACTIVE)
        .values_list("team_id", flat=True)
        .distinct()
    )
    candidate_ids = recent_team_ids | open_incident_team_ids
    if not candidate_ids:
        return []

    eligible: list[int] = []
    for team in Team.objects.filter(id__in=candidate_ids).select_related("organization"):
        if not team.conversations_enabled:
            continue
        settings_dict = team.conversations_settings or {}
        if not settings_dict.get("trends_enabled", True):
            continue
        if not _is_master_flag_enabled(team):
            continue
        eligible.append(team.id)
        if len(eligible) >= MAX_TEAMS_PER_RUN:
            break

    return eligible


@activity.defn
async def ticket_trends_collect_teams_activity(_input: TrendsCoordinatorInput) -> CollectEligibleTeamsOutput:
    """Scan for teams that need a trends analysis run this tick."""
    async with Heartbeater():
        team_ids = await database_sync_to_async(_collect_eligible_teams, thread_sensitive=False)()
    logger.info("ticket_trends coordinator: eligible teams", count=len(team_ids))
    return CollectEligibleTeamsOutput(team_ids=team_ids)


@workflow.defn(name="ticket-trends-coordinator")
class TicketTrendsCoordinatorWorkflow:
    """Coordinator: gates teams, fans out per-team analysis child workflows.

    Child workflow IDs are deterministic per team (`ticket-trends-<team_id>`), so a
    still-running analysis conflicts on its id and the tick skips it — one analysis
    per team at a time. ALLOW_DUPLICATE lets the next tick re-run the team after any
    close (these are recurring evaluations, not one-shots)."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> TrendsCoordinatorInput:
        if not inputs:
            return TrendsCoordinatorInput()
        loaded = json.loads(inputs[0])
        return TrendsCoordinatorInput(**loaded)

    @workflow.run
    async def run(self, _input: TrendsCoordinatorInput) -> TrendsCoordinatorOutput:
        result = await workflow.execute_activity(
            ticket_trends_collect_teams_activity,
            _input,
            start_to_close_timeout=timedelta(minutes=3),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        team_ids = result.team_ids
        if not team_ids:
            return TrendsCoordinatorOutput(eligible_count=0, started_count=0, skipped_count=0)

        started = 0
        skipped = 0
        for team_id in team_ids:
            try:
                await workflow.start_child_workflow(
                    TicketTrendsAnalysisWorkflow.run,
                    TrendsAnalysisInput(team_id=team_id),
                    id=f"ticket-trends-{team_id}",
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                    parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                )
                started += 1
            except WorkflowAlreadyStartedError:
                workflow.logger.info("ticket_trends coordinator: analysis already running", team_id=team_id)
                skipped += 1

        return TrendsCoordinatorOutput(eligible_count=len(team_ids), started_count=started, skipped_count=skipped)
