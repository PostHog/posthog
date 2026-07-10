"""Tests for the poll-duckgres-usage schedule builder.

Mirrors the usage-report schedule tests: invoke the builder with a mocked
client and pin the properties the poller design depends on — the 10-minute
cadence, overlap SKIP (two polls must never run concurrently: a stale
response applied after a newer one would regress the open day until the next
tick), the billing task queue, and a JSON-round-trippable input.
"""

import json
from datetime import timedelta

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.client import ScheduleOverlapPolicy

from posthog.temporal.duckgres_usage.workflow import (
    POLL_DUCKGRES_USAGE_SCHEDULE_ID as SCHEDULE_ID,
    POLL_DUCKGRES_USAGE_WORKFLOW,
)
from posthog.temporal.schedule import create_poll_duckgres_usage_schedule


async def _capture_schedule() -> dict:
    captured: dict = {}

    async def fake_create_schedule(client, schedule_id, schedule, trigger_immediately=False):
        captured["schedule_id"] = schedule_id
        captured["schedule"] = schedule

    with (
        patch("posthog.temporal.schedule.a_schedule_exists", new=AsyncMock(return_value=False)),
        patch("posthog.temporal.schedule.a_create_schedule", new=fake_create_schedule),
    ):
        await create_poll_duckgres_usage_schedule(MagicMock())
    return captured


@pytest.mark.asyncio
async def test_create_and_update_branches_do_not_raise() -> None:
    client = MagicMock()

    with (
        patch("posthog.temporal.schedule.a_schedule_exists", new=AsyncMock(return_value=False)),
        patch("posthog.temporal.schedule.a_create_schedule", new=AsyncMock()) as create_mock,
        patch("posthog.temporal.schedule.a_update_schedule", new=AsyncMock()) as update_mock,
    ):
        await create_poll_duckgres_usage_schedule(client)
        create_mock.assert_awaited_once()
        update_mock.assert_not_awaited()

    with (
        patch("posthog.temporal.schedule.a_schedule_exists", new=AsyncMock(return_value=True)),
        patch("posthog.temporal.schedule.a_create_schedule", new=AsyncMock()) as create_mock,
        patch("posthog.temporal.schedule.a_update_schedule", new=AsyncMock()) as update_mock,
    ):
        await create_poll_duckgres_usage_schedule(client)
        update_mock.assert_awaited_once()
        create_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_schedule_input_round_trips_through_json() -> None:
    captured = await _capture_schedule()

    assert captured["schedule_id"] == SCHEDULE_ID
    raw_input = captured["schedule"].action.args[0]
    assert isinstance(raw_input, dict)
    assert json.loads(json.dumps(raw_input)) == raw_input

    from posthog.temporal.duckgres_usage.types import PollDuckgresUsageInputs

    PollDuckgresUsageInputs(**raw_input)


@pytest.mark.asyncio
async def test_schedule_pins_cadence_overlap_and_queue() -> None:
    captured = await _capture_schedule()
    schedule = captured["schedule"]

    intervals = schedule.spec.intervals
    assert len(intervals) == 1
    assert intervals[0].every == timedelta(minutes=10)
    assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP

    from django.conf import settings

    assert schedule.action.task_queue == settings.BILLING_TASK_QUEUE
    assert schedule.action.workflow == POLL_DUCKGRES_USAGE_WORKFLOW
