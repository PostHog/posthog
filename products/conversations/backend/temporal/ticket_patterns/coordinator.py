from __future__ import annotations

import json

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    import asyncio
    from datetime import timedelta

    from django.utils import timezone

    import structlog

    from posthog.models import Team
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.heartbeat import Heartbeater

    from products.conversations.backend.temporal.ticket_patterns.constants import (
        COORDINATOR_INTERVAL_MINUTES,
        DEFAULT_LOOKBACK_MINUTES,
        DEFAULT_MIN_REQUESTERS,
        DEFAULT_MIN_TICKETS,
        LOOKBACK_MINUTES_RANGE,
        MAX_TEAMS_PER_RUN,
        MIN_REQUESTERS_RANGE,
        MIN_TICKETS_RANGE,
    )
    from products.conversations.backend.temporal.ticket_patterns.detect import ticket_patterns_detect_activity
    from products.conversations.backend.temporal.ticket_patterns.eligibility import is_team_eligible
    from products.conversations.backend.temporal.ticket_patterns.schemas import (
        CollectEligibleTeamsOutput,
        DetectionSettings,
        EligibleTeam,
        PatternsCoordinatorInput,
        PatternsCoordinatorOutput,
    )

logger = structlog.get_logger(__name__)


def _clamp(value: object, default: int, bounds: tuple[int, int]) -> int:
    """A setting is clamped here as well as in the API serializer, because a value can predate
    the serializer's validation or arrive from a direct write."""
    if not isinstance(value, int) or isinstance(value, bool):
        return default
    low, high = bounds
    return max(low, min(high, value))


def _read_settings(settings_dict: dict) -> DetectionSettings:
    return DetectionSettings(
        lookback_minutes=_clamp(
            settings_dict.get("ticket_patterns_lookback_minutes"), DEFAULT_LOOKBACK_MINUTES, LOOKBACK_MINUTES_RANGE
        ),
        min_tickets=_clamp(settings_dict.get("ticket_patterns_min_tickets"), DEFAULT_MIN_TICKETS, MIN_TICKETS_RANGE),
        min_requesters=_clamp(
            settings_dict.get("ticket_patterns_min_requesters"), DEFAULT_MIN_REQUESTERS, MIN_REQUESTERS_RANGE
        ),
    )


def _collect_eligible_teams() -> list[EligibleTeam]:
    """Teams that have opted in and may send ticket text to an LLM."""
    opted_in = list(
        Team.objects.filter(
            conversations_enabled=True,
            conversations_settings__ticket_patterns_enabled=True,
        )
        .select_related("organization")
        .order_by("id")
    )
    # Start each tick where the cap would otherwise keep cutting, so team 51 is not starved
    # forever. Every team is reached within ceil(len / MAX_TEAMS_PER_RUN) ticks.
    if len(opted_in) > MAX_TEAMS_PER_RUN:
        tick = int(timezone.now().timestamp() // (COORDINATOR_INTERVAL_MINUTES * 60))
        offset = (tick * MAX_TEAMS_PER_RUN) % len(opted_in)
        opted_in = opted_in[offset:] + opted_in[:offset]

    eligible: list[EligibleTeam] = []
    for team in opted_in:
        if len(eligible) >= MAX_TEAMS_PER_RUN:
            break
        if not is_team_eligible(team):
            continue
        eligible.append(EligibleTeam(team_id=team.id, settings=_read_settings(team.conversations_settings or {})))
    return eligible


@activity.defn
async def ticket_patterns_collect_eligible_teams_activity(
    _input: PatternsCoordinatorInput,
) -> CollectEligibleTeamsOutput:
    """Find the teams whose recent tickets this tick should scan for a spike."""
    async with Heartbeater():
        teams = await database_sync_to_async(_collect_eligible_teams, thread_sensitive=False)()
    logger.info("ticket_patterns coordinator: eligible teams", count=len(teams))
    return CollectEligibleTeamsOutput(teams=teams)


@workflow.defn(name="ticket-patterns-coordinator")
class TicketPatternsCoordinatorWorkflow:
    """Every 15 minutes: scan each opted-in team's recent tickets for a spike, and emit an event
    for each one found.

    Detection runs as one activity per team, all in flight together. Each is a single LLM call
    that can take tens of seconds, so running them one after another would not fit in the tick.
    One team's failure is contained: its activity exhausts its own retries and the rest still
    report. Nothing is persisted, so a whole failed tick simply means the next one sees the same
    window.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> PatternsCoordinatorInput:
        if not inputs:
            return PatternsCoordinatorInput()
        return PatternsCoordinatorInput(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, _input: PatternsCoordinatorInput) -> PatternsCoordinatorOutput:
        collected = await workflow.execute_activity(
            ticket_patterns_collect_eligible_teams_activity,
            _input,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if not collected.teams:
            return PatternsCoordinatorOutput(eligible_team_count=0, detected_count=0)

        results = await asyncio.gather(
            *(
                workflow.execute_activity(
                    ticket_patterns_detect_activity,
                    team,
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                for team in collected.teams
            ),
            return_exceptions=True,
        )

        detected = 0
        for team, result in zip(collected.teams, results):
            if isinstance(result, BaseException):
                workflow.logger.warning(
                    "ticket_patterns coordinator: team detection failed",
                    extra={"team_id": team.team_id, "error": str(result)},
                )
                continue
            detected += len(result.clusters)

        return PatternsCoordinatorOutput(eligible_team_count=len(collected.teams), detected_count=detected)
