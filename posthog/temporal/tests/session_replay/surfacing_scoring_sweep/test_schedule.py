"""Schedule wiring for the surfacing scoring sweep."""

from __future__ import annotations

from django.conf import settings

from posthog.temporal.session_replay.surfacing_scoring_sweep.constants import (
    SCHEDULE_INTERVAL,
    WORKFLOW_EXECUTION_TIMEOUT,
    WORKFLOW_NAME,
)
from posthog.temporal.session_replay.surfacing_scoring_sweep.schedule import _build_schedule


class TestSurfacingScoringSchedule:
    def test_schedule_targets_dedicated_task_queue(self) -> None:
        schedule = _build_schedule()
        action = schedule.action
        assert action.task_queue == settings.SURFACING_SCORING_SWEEP_TASK_QUEUE

    def test_schedule_starts_score_sessions_batch_workflow(self) -> None:
        schedule = _build_schedule()
        assert schedule.action.workflow == WORKFLOW_NAME

    def test_schedule_skips_overlapping_ticks(self) -> None:
        from temporalio.client import ScheduleOverlapPolicy

        schedule = _build_schedule()
        assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP

    def test_schedule_interval_and_execution_timeout(self) -> None:
        schedule = _build_schedule()
        assert schedule.spec.intervals[0].every == SCHEDULE_INTERVAL
        assert schedule.action.execution_timeout == WORKFLOW_EXECUTION_TIMEOUT
