from __future__ import annotations

import json

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    import asyncio
    from datetime import timedelta

    from django.utils import timezone

    import structlog

    from posthog.models import Team
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.heartbeat import Heartbeater

    from products.conversations.backend.temporal.ticket_patterns.constants import (
        COLLECTION_BUDGET_SECONDS,
        COORDINATOR_INTERVAL_MINUTES,
        DEFAULT_LOOKBACK_MINUTES,
        DEFAULT_MIN_REQUESTERS,
        DEFAULT_MIN_TICKETS,
        DETECTION_BATCH_BUDGET_SECONDS,
        DETECTION_HEARTBEAT_TIMEOUT_SECONDS,
        LOOKBACK_MINUTES_RANGE,
        MAX_CONCURRENT_DETECTIONS,
        MAX_TEAMS_PER_RUN,
        MAX_TEAMS_SCANNED_PER_RUN,
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
    """Teams that have opted in and may send ticket text to an LLM.

    Hydration is bounded by MAX_TEAMS_SCANNED_PER_RUN rather than by the number of opt-ins, so a
    wide rollout cannot turn a tick into a full scan of every opted-in team and its organization.
    The window starts where the previous tick stopped, so a team past the cap waits for its turn
    instead of never being reached.
    """
    opted_in = (
        Team.objects.filter(
            conversations_enabled=True,
            conversations_settings__ticket_patterns_enabled=True,
        )
        .select_related("organization")
        .order_by("id")
    )
    total = opted_in.count()
    if not total:
        return []

    # Start each tick where the cap would otherwise keep cutting, so team 51 is not starved
    # forever. Starvation starts as soon as there are more opt-ins than one tick reports on, so
    # the window moves from that point rather than from the larger hydration budget. This reaches
    # every team within ceil(total / MAX_TEAMS_PER_RUN) ticks only while the schedule fires every
    # tick, because the offset counts wall-clock ticks rather than runs that happened. Fires
    # dropped on a fixed period can pin the offset and starve the rest: 100 teams with every
    # second fire dropped holds it at 0 forever. The schedule's execution timeout is what stops a
    # run outliving its interval and dropping the next fire. Holding the guarantee through a
    # dropped fire instead would need a stored cursor, which this design does without.
    if total > MAX_TEAMS_PER_RUN:
        tick = int(timezone.now().timestamp() // (COORDINATOR_INTERVAL_MINUTES * 60))
        offset = (tick * MAX_TEAMS_PER_RUN) % total
    else:
        offset = 0

    scan = min(total, MAX_TEAMS_SCANNED_PER_RUN)
    window = list(opted_in[offset : offset + scan])
    # Wrap, so the teams at the end of the ordering share a window with those at the start rather
    # than being scanned only by the one tick whose offset lands on them.
    shortfall = scan - len(window)
    if shortfall > 0:
        window += list(opted_in[:shortfall])

    eligible: list[EligibleTeam] = []
    for team in window:
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
            start_to_close_timeout=timedelta(seconds=COLLECTION_BUDGET_SECONDS),
            # Retries included, so a slow collection cannot eat the time the batches need.
            schedule_to_close_timeout=timedelta(seconds=COLLECTION_BUDGET_SECONDS),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if not collected.teams:
            return PatternsCoordinatorOutput(eligible_team_count=0, detected_count=0)

        detected = 0
        failed = 0
        # In batches rather than all at once: the task queue is shared, and a worker accepts a
        # bounded number of activities, so one wide tick would otherwise hold a whole worker's
        # capacity in slow LLM calls while unrelated work waits behind it.
        for start in range(0, len(collected.teams), MAX_CONCURRENT_DETECTIONS):
            batch = collected.teams[start : start + MAX_CONCURRENT_DETECTIONS]
            results = await asyncio.gather(
                *(
                    workflow.execute_activity(
                        ticket_patterns_detect_activity,
                        team,
                        start_to_close_timeout=timedelta(seconds=DETECTION_BATCH_BUDGET_SECONDS),
                        # Retries included, so a team that keeps failing cannot spend the budget
                        # the batches after it need.
                        schedule_to_close_timeout=timedelta(seconds=DETECTION_BATCH_BUDGET_SECONDS),
                        # The worker stops an attempt on its own only when start_to_close runs out,
                        # counted from when it picked the task up. An attempt that waited in the
                        # shared queue times out on the server first, and only a heartbeat brings
                        # that cancel back, so without one it keeps its slot into the next batch.
                        heartbeat_timeout=timedelta(seconds=DETECTION_HEARTBEAT_TIMEOUT_SECONDS),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                    for team in batch
                ),
                return_exceptions=True,
            )
            for team, result in zip(batch, results):
                if isinstance(result, BaseException):
                    failed += 1
                    workflow.logger.warning(
                        "ticket_patterns coordinator: team detection failed",
                        extra={"team_id": team.team_id, "error": str(result)},
                    )
                    continue
                detected += len(result.clusters)

        # One team's failure is its own. Every team failing is the gateway or the worker, and a
        # run that reports success for it would look exactly like a quiet period with no spikes.
        if failed == len(collected.teams):
            raise ApplicationError(
                f"Ticket pattern detection failed for all {failed} eligible teams",
                type="AllTeamsFailed",
            )

        return PatternsCoordinatorOutput(
            eligible_team_count=len(collected.teams), detected_count=detected, failed_team_count=failed
        )
