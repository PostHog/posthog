from __future__ import annotations

import datetime as dt
from collections.abc import Collection
from typing import Literal

import structlog

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.temporal.health_checks.rollups.fill import DayOverRowCap, fill_day
from posthog.temporal.health_checks.rollups.framework import DailyRollup
from posthog.temporal.health_checks.rollups.freshness import invalidate_published_days
from posthog.temporal.health_checks.rollups.store import (
    day_stats,
    delete_days_before,
    delete_rows_of_deleted_teams,
    publish_day,
)
from posthog.temporal.health_checks.rollups.validation import day_moved, refusal_reason

logger = structlog.get_logger(__name__)

MEDIAN_HISTORY_DAYS = 7

RollupDayMode = Literal["publish", "refresh"]
RollupDayOutcome = Literal["published", "unchanged"]


@frozen
class RollupDay:
    day: dt.date
    mode: RollupDayMode


@frozen
class RollupDayResult:
    day: dt.date
    outcome: RollupDayOutcome
    rows: int
    events: int


class RollupDayRefused(Exception):
    """The filled day looks wrong, so the published day stays as it was."""


def plan_scheduled_days(
    rollup: type[DailyRollup], *, today: dt.date, published: Collection[dt.date]
) -> list[RollupDay]:
    """The days one scheduled run fills, newest first.

    It publishes yesterday and refreshes the day before, to pick up late events. It also publishes
    every missing day that retention keeps, so the first run after a deploy and the run after an
    outage fill the gap with no manual backfill.
    """
    yesterday = today - dt.timedelta(days=1)
    plan = [RollupDay(day=yesterday, mode="publish"), RollupDay(day=yesterday - dt.timedelta(days=1), mode="refresh")]
    oldest_kept = today - dt.timedelta(days=rollup.retention_days)
    day = yesterday - dt.timedelta(days=2)
    while day >= oldest_kept:
        if day not in published:
            plan.append(RollupDay(day=day, mode="publish"))
        day -= dt.timedelta(days=1)
    return plan


def plan_requested_days(days: Collection[dt.date], *, today: dt.date) -> list[RollupDay]:
    future = sorted(day for day in days if day >= today)
    if future:
        raise ValueError(f"Cannot fill a day that has not ended: {', '.join(day.isoformat() for day in future)}")
    return [RollupDay(day=day, mode="publish") for day in sorted(set(days))]


def published_days_in_retention(rollup: type[DailyRollup], *, today: dt.date) -> set[dt.date]:
    kept = [today - dt.timedelta(days=offset) for offset in range(1, rollup.retention_days + 1)]
    return set(day_stats(rollup, kept))


def _live_team_ids() -> set[int]:
    return set(Team.objects.values_list("id", flat=True))


def run_rollup_day(rollup: type[DailyRollup], step: RollupDay, *, force: bool = False) -> RollupDayResult:
    """Fill one day of one rollup and publish it unless it is refused or unchanged.

    Every slow part, the ClickHouse reads, runs before the Postgres transaction opens.
    """
    try:
        fill = fill_day(rollup, step.day, _live_team_ids())
    except DayOverRowCap as error:
        logger.warning("daily rollup day refused", table=rollup.table(), day=step.day.isoformat(), reason=str(error))
        raise RollupDayRefused(f"Refused to publish {rollup.table()} for {step.day.isoformat()}: {error}") from error
    try:
        if step.mode == "refresh" and not day_moved(day_stats(rollup, [step.day]).get(step.day), fill):
            logger.info(
                "daily rollup day unchanged", table=rollup.table(), day=step.day.isoformat(), rows=fill.row_count
            )
            return RollupDayResult(day=step.day, outcome="unchanged", rows=fill.row_count, events=fill.event_count)

        history_days = [step.day - dt.timedelta(days=offset) for offset in range(1, MEDIAN_HISTORY_DAYS + 1)]
        stats = day_stats(rollup, history_days)
        history = [stats[history_day] for history_day in history_days if history_day in stats]
        reason = refusal_reason(rollup, fill, history, force=force)
        if reason is not None:
            logger.warning("daily rollup day refused", table=rollup.table(), day=step.day.isoformat(), reason=reason)
            raise RollupDayRefused(f"Refused to publish {rollup.table()} for {step.day.isoformat()}: {reason}")

        publish_day(rollup, fill)
        invalidate_published_days(rollup.model)
        return RollupDayResult(day=step.day, outcome="published", rows=fill.row_count, events=fill.event_count)
    finally:
        fill.close()


def clean_up(rollup: type[DailyRollup], *, today: dt.date) -> int:
    """Delete the days retention no longer keeps and the rows of deleted environments."""
    deleted = delete_days_before(rollup, today - dt.timedelta(days=rollup.retention_days))
    deleted += delete_rows_of_deleted_teams(rollup)
    if deleted:
        invalidate_published_days(rollup.model)
    return deleted
