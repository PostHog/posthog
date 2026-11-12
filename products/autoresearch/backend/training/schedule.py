"""When the next scheduled research run of a pipeline is due.

Research has two phases, derived from the pipeline's training runs and never stored.
Explore starts a run on each sweep until a completed run does not promote its best model,
or until ``EXPLORE_RUN_LIMIT`` research runs have run. Maintain starts one run
``research_interval_days`` after the latest training run of any kind, so a manual run resets the clock.

A ``bootstrapping`` pipeline whose first champion rolled back follows the same schedule
(``awaiting_first_champion()``).

When a project has more runs due than free training runs, ``kickoff_rank()`` orders the due pipelines.
"""

from collections.abc import Iterable
from datetime import UTC, datetime, time, timedelta
from typing import Literal
from uuid import UUID

from django.db.models import Exists, OuterRef, Q

from posthog.dataclasses import frozen

from ..models import AutoresearchModel, AutoresearchPipeline, AutoresearchTrainingRun

# Research runs before explore ends, if no run stopped it first. Rescue runs do not count.
EXPLORE_RUN_LIMIT = 5

TrainingPhase = Literal["explore", "maintain"]

# The order in which a project's due pipelines take its free training runs, first to last.
NO_CHAMPION_PRIORITY = 0
RESCUE_PRIORITY = 1
RESEARCH_PRIORITY = 2

KickoffRank = tuple[int, datetime, str]


@frozen
class ScheduleRun:
    """The fields of one training run that the schedule reads."""

    kickoff_reason: str | None
    status: str
    champion_promoted: bool | None
    created_at: datetime


@frozen
class ResearchSchedule:
    phase: TrainingPhase
    # The start of the UTC day from which the sweep may start the next scheduled run.
    # None when the pipeline has no scheduled research.
    next_research_at: datetime | None

    def is_due(self, now: datetime) -> bool:
        return self.next_research_at is not None and now >= self.next_research_at


def _start_of_day(moment: datetime) -> datetime:
    return datetime.combine(moment.astimezone(UTC).date(), time.min, tzinfo=UTC)


def _ends_explore(run: ScheduleRun) -> bool:
    return run.status == AutoresearchTrainingRun.Status.COMPLETED and run.champion_promoted is False


def research_schedule(
    *, research_interval_days: int | None, pipeline_created_at: datetime, runs: Iterable[ScheduleRun]
) -> ResearchSchedule:
    runs = list(runs)
    research_runs = [
        run
        for run in runs
        if run.kickoff_reason != AutoresearchTrainingRun.KickoffReason.RESCUE
        and run.status in (AutoresearchTrainingRun.Status.COMPLETED, AutoresearchTrainingRun.Status.FAILED)
    ]
    exploring = len(research_runs) < EXPLORE_RUN_LIMIT and not any(_ends_explore(run) for run in research_runs)
    phase: TrainingPhase = "explore" if exploring else "maintain"
    if research_interval_days is None:
        return ResearchSchedule(phase=phase, next_research_at=None)
    latest = max((run.created_at for run in runs), default=None)
    if latest is None:
        return ResearchSchedule(phase=phase, next_research_at=_start_of_day(pipeline_created_at))
    # By calendar day, like the scoring cadence: a run starts some time after the daily tick, and an
    # elapsed-time comparison would push each run one sweep later than the interval.
    gap = timedelta(days=1 if exploring else research_interval_days)
    return ResearchSchedule(phase=phase, next_research_at=_start_of_day(latest) + gap)


def scheduled_kickoff_reason(schedule: ResearchSchedule, now: datetime) -> AutoresearchTrainingRun.KickoffReason | None:
    """Why the sweep starts a research run now, or None when none is due."""
    if schedule.next_research_at is None:
        return None
    if schedule.phase == "explore":
        return AutoresearchTrainingRun.KickoffReason.EXPLORE
    if schedule.is_due(now):
        return AutoresearchTrainingRun.KickoffReason.SCHEDULED
    return None


def kickoff_rank(*, priority: int, next_research_at: datetime | None, pipeline_id: UUID) -> KickoffRank:
    """The sort key of a due pipeline in the queue for the project's free training runs. Lower comes first.

    A pipeline with no champion comes first, because it scores nobody until a run finds one. A champion
    that cannot score comes next, then the pipeline whose research run has waited longest. The id breaks ties.
    """
    return (priority, next_research_at or datetime.max.replace(tzinfo=UTC), str(pipeline_id))


def schedule_runs_for(pipeline_ids: Iterable[UUID], team_id: int) -> dict[UUID, list[ScheduleRun]]:
    """The schedule fields of every training run of these pipelines, in one query."""
    runs: dict[UUID, list[ScheduleRun]] = {}
    rows = (
        AutoresearchTrainingRun.objects.for_team(team_id)
        .filter(pipeline_id__in=list(pipeline_ids))
        .values_list("pipeline_id", "kickoff_reason", "status", "summary__champion_promoted", "created_at")
    )
    for pipeline_id, kickoff_reason, status, champion_promoted, created_at in rows:
        runs.setdefault(pipeline_id, []).append(
            ScheduleRun(
                kickoff_reason=kickoff_reason,
                status=status,
                champion_promoted=champion_promoted if isinstance(champion_promoted, bool) else None,
                created_at=created_at,
            )
        )
    return runs


def awaiting_first_champion() -> Q:
    """Filter pipelines to the ``bootstrapping`` ones that wait for a scheduled run to find a first champion.

    A first champion that fails its fit or its scorability check rolls back, and the pipeline goes
    back to ``bootstrapping`` with a completed run. Such a pipeline has no champion and no pending
    or running training run. Without scheduled research it stays in this state.
    """
    run_of_pipeline = AutoresearchTrainingRun.all_teams.filter(team_id=OuterRef("team_id"), pipeline_id=OuterRef("pk"))
    return Q(
        Exists(run_of_pipeline.filter(status=AutoresearchTrainingRun.Status.COMPLETED)),
        ~Exists(
            run_of_pipeline.filter(
                status__in=[AutoresearchTrainingRun.Status.PENDING, AutoresearchTrainingRun.Status.RUNNING]
            )
        ),
        ~Exists(
            AutoresearchModel.all_teams.filter(
                team_id=OuterRef("team_id"), pipeline_id=OuterRef("pk"), role=AutoresearchModel.Role.CHAMPION
            )
        ),
        status=AutoresearchPipeline.Status.BOOTSTRAPPING,
    )
