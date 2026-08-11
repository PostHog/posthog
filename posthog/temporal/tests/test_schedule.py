import pytest
from unittest import mock

from django.conf import settings
from django.test import override_settings

from temporalio.client import Schedule, ScheduleActionStartWorkflow

from posthog.temporal.schedule import create_wa_digest_notification_schedule, create_wa_weekly_digest_schedule


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
