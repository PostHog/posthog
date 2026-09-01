import pytest
from unittest import mock

from django.conf import settings
from django.test import override_settings

from temporalio.client import Schedule, ScheduleActionStartWorkflow

from posthog.temporal.ai_observability.trace_clustering import constants as trace_clustering_constants
from posthog.temporal.ai_observability.trace_summarization import constants as trace_summarization_constants
from posthog.temporal.schedule import (
    cleanup_non_cloud_ai_observability_schedules,
    create_wa_digest_notification_schedule,
    create_wa_weekly_digest_schedule,
)


# Both WA digest schedules pin their task queue, and the worker registers those workflows on
# WEEKLY_DIGEST_TASK_QUEUE. If a later edit repoints or hardcodes only the schedule side, the
# schedules fire into a queue nobody polls, which stays invisible for a week because both digests are
# weekly. The setting is overridden to a distinct value because every task queue setting collapses to
# one shared dev queue under DEBUG, so asserting against the un-overridden symbol would also pass if
# the schedules pointed at some other queue's setting.
@pytest.mark.asyncio
@override_settings(WEEKLY_DIGEST_TASK_QUEUE="weekly-digest-task-queue-under-test")
async def test_wa_digest_schedules_target_the_weekly_digest_queue() -> None:
    captured: list[Schedule] = []

    with (
        mock.patch("posthog.temporal.schedule.a_schedule_exists", new=mock.AsyncMock(return_value=False)),
        mock.patch(
            "posthog.temporal.schedule.a_create_schedule",
            new=mock.AsyncMock(side_effect=lambda client, schedule_id, schedule, **kwargs: captured.append(schedule)),
        ),
    ):
        await create_wa_weekly_digest_schedule(mock.MagicMock())
        await create_wa_digest_notification_schedule(mock.MagicMock())

    task_queues: list[str] = []
    for schedule in captured:
        assert isinstance(schedule.action, ScheduleActionStartWorkflow)
        task_queues.append(schedule.action.task_queue)

    assert task_queues == [settings.WEEKLY_DIGEST_TASK_QUEUE] * 2


# The reaper converges self-hosted instances that still hold clustering/summarization schedule rows a
# prior release created. It must delete all four there, and nothing where the coordinators still
# register, which is cloud and a local DEBUG install.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cloud_deployment,debug,expected_deleted",
    [
        (
            None,
            False,
            [
                trace_summarization_constants.COORDINATOR_SCHEDULE_ID,
                trace_summarization_constants.GENERATION_COORDINATOR_SCHEDULE_ID,
                trace_clustering_constants.COORDINATOR_SCHEDULE_ID,
                trace_clustering_constants.GENERATION_COORDINATOR_SCHEDULE_ID,
            ],
        ),
        ("US", False, []),
        (None, True, []),
    ],
)
async def test_cleanup_non_cloud_ai_observability_schedules(cloud_deployment, debug, expected_deleted) -> None:
    deleted: list[str] = []

    with (
        override_settings(CLOUD_DEPLOYMENT=cloud_deployment, DEBUG=debug),
        mock.patch("posthog.temporal.schedule.a_schedule_exists", new=mock.AsyncMock(return_value=True)),
        mock.patch(
            "posthog.temporal.schedule.a_delete_schedule",
            new=mock.AsyncMock(side_effect=lambda client, schedule_id: deleted.append(schedule_id)),
        ),
    ):
        await cleanup_non_cloud_ai_observability_schedules(mock.MagicMock())

    assert deleted == expected_deleted
