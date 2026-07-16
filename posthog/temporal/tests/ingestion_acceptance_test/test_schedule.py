from __future__ import annotations

from datetime import timedelta

from django.conf import settings

from temporalio.client import ScheduleActionStartWorkflow

from posthog.temporal.ingestion_acceptance_test.schedule import WORKFLOW_NAME, _build_schedule, _lane_schedule_id
from posthog.temporal.ingestion_acceptance_test.types import IngestionAcceptanceTestInput


def _action(inputs: IngestionAcceptanceTestInput) -> ScheduleActionStartWorkflow:
    action = _build_schedule(inputs).action
    assert isinstance(action, ScheduleActionStartWorkflow)
    return action


class TestBuildSchedule:
    def test_targets_general_purpose_queue(self) -> None:
        assert _action(IngestionAcceptanceTestInput()).task_queue == settings.GENERAL_PURPOSE_TASK_QUEUE

    def test_starts_ingestion_acceptance_workflow(self) -> None:
        assert _action(IngestionAcceptanceTestInput()).workflow == WORKFLOW_NAME

    def test_passes_lane_to_workflow(self) -> None:
        action = _action(IngestionAcceptanceTestInput(lane="turbo"))
        assert list(action.args) == [IngestionAcceptanceTestInput(lane="turbo")]

    def test_interval_is_15_minutes(self) -> None:
        schedule = _build_schedule(IngestionAcceptanceTestInput())
        assert schedule.spec.intervals[0].every == timedelta(minutes=15)


class TestLaneScheduleId:
    def test_lane_schedule_id_format(self) -> None:
        assert _lane_schedule_id("turbo") == "ingestion-acceptance-test-turbo-schedule"


class TestDeployRegistry:
    def test_schedule_is_wired_into_deploy_registry(self) -> None:
        # Without this entry the schedule is never upserted on deploy and the
        # workflow never fires. Guards that exact regression.
        from posthog.temporal.ingestion_acceptance_test.schedule import (  # noqa: PLC0415
            create_ingestion_acceptance_test_schedule,
        )
        from posthog.temporal.schedule import schedules  # noqa: PLC0415 — heavy registry import, kept off module load

        assert create_ingestion_acceptance_test_schedule in schedules
