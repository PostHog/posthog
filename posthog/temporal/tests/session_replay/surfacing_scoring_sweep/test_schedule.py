from __future__ import annotations

from django.conf import settings

from temporalio.client import ScheduleActionStartWorkflow

from posthog.temporal.session_replay.surfacing_scoring_sweep.constants import (
    SCHEDULE_INTERVAL,
    WORKFLOW_EXECUTION_TIMEOUT,
    WORKFLOW_NAME,
)
from posthog.temporal.session_replay.surfacing_scoring_sweep.schedule import _build_schedule


def _start_workflow_action() -> ScheduleActionStartWorkflow:
    action = _build_schedule().action
    assert isinstance(action, ScheduleActionStartWorkflow)
    return action


class TestSurfacingScoringSchedule:
    def test_schedule_targets_dedicated_task_queue(self) -> None:
        assert _start_workflow_action().task_queue == settings.SURFACING_SCORING_SWEEP_TASK_QUEUE

    def test_schedule_starts_score_sessions_batch_workflow(self) -> None:
        assert _start_workflow_action().workflow == WORKFLOW_NAME

    def test_schedule_skips_overlapping_ticks(self) -> None:
        from temporalio.client import ScheduleOverlapPolicy

        schedule = _build_schedule()
        assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP

    def test_schedule_interval_and_execution_timeout(self) -> None:
        schedule = _build_schedule()
        action = schedule.action
        assert isinstance(action, ScheduleActionStartWorkflow)
        assert schedule.spec.intervals[0].every == SCHEDULE_INTERVAL
        assert action.execution_timeout == WORKFLOW_EXECUTION_TIMEOUT

    def test_schedule_is_wired_into_deploy_registry(self) -> None:
        # Without this entry the schedule is never upserted on deploy and the
        # workflow never fires. Guards that exact regression.
        from posthog.temporal.schedule import schedules  # noqa: PLC0415 — heavy registry import, kept off module load
        from posthog.temporal.session_replay.surfacing_scoring_sweep.schedule import (  # noqa: PLC0415
            create_surfacing_scoring_sweep_schedule,
        )

        assert create_surfacing_scoring_sweep_schedule in schedules
