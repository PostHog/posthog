from __future__ import annotations

import json

from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    import math
    from datetime import UTC, datetime, timedelta

    import structlog

    from posthog.models import Team
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.heartbeat import Heartbeater

    from products.conversations.backend.temporal.patterns.constants import (
        COORDINATOR_INTERVAL_MINUTES,
        MAX_TEAMS_PER_RUN,
    )
    from products.conversations.backend.temporal.patterns.detect import TicketPatternDetectWorkflow
    from products.conversations.backend.temporal.patterns.eligibility import is_pattern_detection_enabled
    from products.conversations.backend.temporal.patterns.schemas import (
        CollectEligibleTeamsOutput,
        PatternCoordinatorInput,
        PatternCoordinatorOutput,
        TeamPatternInput,
    )

logger = structlog.get_logger(__name__)


def floor_to_tick(now: datetime) -> datetime:
    floored_minute = (now.minute // COORDINATOR_INTERVAL_MINUTES) * COORDINATOR_INTERVAL_MINUTES
    return now.replace(minute=floored_minute, second=0, microsecond=0)


def tick_bucket(now: datetime) -> str:
    return floor_to_tick(now).isoformat()


def build_detect_workflow_id(team_id: int, tick: str) -> str:
    return f"ticket-patterns-detect-{team_id}-{tick}"


def _collect_eligible_teams(now: datetime) -> list[TeamPatternInput]:
    # The JSON filter does the cheap part in SQL; the flag evaluation is a network call per team,
    # so only teams that opted in pay it.
    teams = (
        Team.objects.select_related("organization")
        .filter(conversations_enabled=True, conversations_settings__pattern_detection_enabled=True)
        .order_by("id")
    )
    # A team stays eligible forever, so taking the lowest ids on every tick would leave everyone
    # past the cap waiting for a turn that never comes. Each tick takes the next page and wraps at
    # the end, which is what makes the overflow roll instead of starve.
    total = teams.count()
    if total > MAX_TEAMS_PER_RUN:
        pages = math.ceil(total / MAX_TEAMS_PER_RUN)
        page = int(floor_to_tick(now).timestamp()) // (COORDINATOR_INTERVAL_MINUTES * 60) % pages
        teams = teams[page * MAX_TEAMS_PER_RUN : (page + 1) * MAX_TEAMS_PER_RUN]
    tick = tick_bucket(now)
    eligible: list[TeamPatternInput] = []
    for team in teams.iterator(chunk_size=MAX_TEAMS_PER_RUN):
        if is_pattern_detection_enabled(team):
            eligible.append(TeamPatternInput(team_id=team.id, tick=tick))
    return eligible


@activity.defn
async def patterns_collect_eligible_teams_activity(_input: PatternCoordinatorInput) -> CollectEligibleTeamsOutput:
    async with Heartbeater():
        teams = await database_sync_to_async(_collect_eligible_teams, thread_sensitive=False)(datetime.now(UTC))
    logger.info("ticket_patterns coordinator: eligible teams", count=len(teams))
    return CollectEligibleTeamsOutput(teams=teams)


@workflow.defn(name="ticket-patterns-coordinator")
class TicketPatternCoordinatorWorkflow:
    """Every 15 minutes: find teams with pattern detection on and fan out one child per team.

    Child ids embed the tick bucket, so two coordinator runs inside one bucket collapse to one child
    per team, while a child stuck from an earlier bucket cannot block the team forever.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> PatternCoordinatorInput:
        if not inputs:
            return PatternCoordinatorInput()
        return PatternCoordinatorInput(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, _input: PatternCoordinatorInput) -> PatternCoordinatorOutput:
        result = await workflow.execute_activity(
            patterns_collect_eligible_teams_activity,
            _input,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        started = 0
        skipped = 0
        for item in result.teams:
            child_id = build_detect_workflow_id(item.team_id, item.tick)
            try:
                await workflow.start_child_workflow(
                    TicketPatternDetectWorkflow.run,
                    item,
                    id=child_id,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                    parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                )
                started += 1
            except WorkflowAlreadyStartedError:
                skipped += 1

        return PatternCoordinatorOutput(eligible_count=len(result.teams), started_count=started, skipped_count=skipped)
