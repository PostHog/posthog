from __future__ import annotations

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from datetime import datetime, timedelta

    import structlog

    from posthog.models import Team
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.heartbeat import Heartbeater

    from products.conversations.backend.models import Ticket, TicketPattern
    from products.conversations.backend.pattern_delivery import deliver_opened, deliver_resolved
    from products.conversations.backend.pattern_detection import (
        baselines_refreshed_at,
        refresh_baselines,
        run_detection,
    )
    from products.conversations.backend.temporal.patterns.constants import (
        BASELINE_MIN_HISTORY_DAYS,
        BASELINE_REFRESH_MINUTES,
        BASELINE_SAMPLE_WINDOW_DAYS,
    )
    from products.conversations.backend.temporal.patterns.eligibility import is_pattern_detection_enabled
    from products.conversations.backend.temporal.patterns.schemas import TeamPatternInput, TeamPatternOutput

logger = structlog.get_logger(__name__)


def _baselines_are_stale(team: Team, now: datetime) -> bool:
    latest = baselines_refreshed_at(team)
    if latest is not None:
        return latest < now - timedelta(minutes=BASELINE_REFRESH_MINUTES)
    oldest_ticket = Ticket.objects.filter(team=team).order_by("created_at").values_list("created_at", flat=True).first()
    return oldest_ticket is not None and oldest_ticket <= now - timedelta(days=BASELINE_MIN_HISTORY_DAYS)


def _deliver(team: Team, opened: tuple, auto_resolved: tuple) -> None:
    # Side effects run once the detection writes are committed and never inside them, so a failing
    # Slack post or notification cannot roll back a pattern. Each helper is idempotent; a retried
    # activity re-delivers safely.
    patterns = {p.id: p for p in TicketPattern.objects.for_team(team.id).filter(id__in=[*opened, *auto_resolved])}
    for pattern_id in opened:
        pattern = patterns.get(pattern_id)
        if pattern is None:
            continue
        try:
            deliver_opened(pattern)
        except Exception:
            logger.exception("ticket_patterns: delivery failed", team_id=team.id, pattern_id=str(pattern_id))
    for pattern_id in auto_resolved:
        pattern = patterns.get(pattern_id)
        if pattern is not None:
            deliver_resolved(pattern, "auto")


def _detect_for_team(input: TeamPatternInput) -> TeamPatternOutput:
    team = Team.objects.select_related("organization").filter(id=input.team_id).first()
    # Children run detached and may retry much later, so eligibility is re-checked here, not trusted
    # from the coordinator.
    if team is None or not is_pattern_detection_enabled(team):
        return TeamPatternOutput()
    now = datetime.fromisoformat(input.tick)

    refreshed = False
    if _baselines_are_stale(team, now):
        refresh_baselines(team, now=now, sample_window_days=BASELINE_SAMPLE_WINDOW_DAYS)
        refreshed = True

    outcome = run_detection(team, now=now)
    _deliver(team, outcome.opened, outcome.auto_resolved)
    logger.info(
        "ticket_patterns: detection run",
        team_id=team.id,
        opened=len(outcome.opened),
        updated=len(outcome.updated),
        suppressed=len(outcome.suppressed),
        auto_resolved=len(outcome.auto_resolved),
        baselines_refreshed=refreshed,
    )
    return TeamPatternOutput(
        opened=len(outcome.opened),
        updated=len(outcome.updated),
        suppressed=len(outcome.suppressed),
        auto_resolved=len(outcome.auto_resolved),
        baselines_refreshed=refreshed,
    )


@activity.defn
async def detect_ticket_patterns_activity(input: TeamPatternInput) -> TeamPatternOutput:
    async with Heartbeater():
        return await database_sync_to_async(_detect_for_team, thread_sensitive=False)(input)


@workflow.defn(name="ticket-patterns-detect")
class TicketPatternDetectWorkflow:
    """One detection pass for one team: a single activity so ticket text never crosses an activity
    boundary."""

    @workflow.run
    async def run(self, input: TeamPatternInput) -> TeamPatternOutput:
        return await workflow.execute_activity(
            detect_ticket_patterns_activity,
            input,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
