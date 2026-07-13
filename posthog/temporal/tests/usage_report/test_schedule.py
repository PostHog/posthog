"""Regression tests for the usage-report schedule builders.

The previous version of this code passed `dataclasses.asdict(...)` on
`RunUsageReportsInputs` *after* it was migrated to pydantic — that
silently raised `TypeError` the first time the worker registered the
schedule, and *no* test caught it because nothing in the suite ever
imported and called the schedule-creation function.

These tests close that gap: they actually invoke the functions with a
mocked client and assert they (a) don't raise, (b) hand Temporal a
JSON-serializable input, and (c) carry the right `day_offset` — the
intraday schedule reports today, the finalizer reports yesterday.
"""

import json
from datetime import timedelta

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.temporal.schedule import create_finalize_usage_reports_schedule, create_run_usage_reports_schedule

SCHEDULE_CASES = [
    (create_run_usage_reports_schedule, "run-usage-reports-schedule", 0),
    (create_finalize_usage_reports_schedule, "finalize-usage-reports-schedule", 1),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("create_schedule_fn,schedule_id,expected_day_offset", SCHEDULE_CASES)
async def test_create_usage_reports_schedules_do_not_raise(
    create_schedule_fn, schedule_id, expected_day_offset
) -> None:
    """The schedule-builders must not blow up when called — covers both the
    `a_schedule_exists is False` (create) and `True` (update) branches.
    """
    client = MagicMock()

    # First-time registration: schedule doesn't exist → `a_create_schedule` runs.
    with (
        patch("posthog.temporal.schedule.a_schedule_exists", new=AsyncMock(return_value=False)),
        patch("posthog.temporal.schedule.a_create_schedule", new=AsyncMock()) as create_mock,
        patch("posthog.temporal.schedule.a_update_schedule", new=AsyncMock()) as update_mock,
    ):
        await create_schedule_fn(client)
        create_mock.assert_awaited_once()
        update_mock.assert_not_awaited()

    # Re-registration: schedule already exists → `a_update_schedule` runs.
    with (
        patch("posthog.temporal.schedule.a_schedule_exists", new=AsyncMock(return_value=True)),
        patch("posthog.temporal.schedule.a_create_schedule", new=AsyncMock()) as create_mock,
        patch("posthog.temporal.schedule.a_update_schedule", new=AsyncMock()) as update_mock,
    ):
        await create_schedule_fn(client)
        update_mock.assert_awaited_once()
        create_mock.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("create_schedule_fn,schedule_id,expected_day_offset", SCHEDULE_CASES)
async def test_usage_reports_schedule_input_is_json_serializable(
    create_schedule_fn, schedule_id, expected_day_offset
) -> None:
    """Temporal serializes the `ScheduleActionStartWorkflow` input via the
    data converter. Even with the pydantic data converter, JSON-encoding
    must round-trip — otherwise registration fails the moment it hits
    the wire. Catches the original `dataclasses.asdict(pydantic_model)`
    bug that landed on this branch.

    Also pins each schedule's `day_offset`: the intraday schedule must
    report today (0) and the finalizer yesterday (1) — swapping or
    dropping these silently sends billing the wrong day.
    """
    captured: dict = {}

    async def fake_create_schedule(client, schedule_id, schedule, trigger_immediately=False):
        captured["schedule_id"] = schedule_id
        captured["schedule"] = schedule

    with (
        patch("posthog.temporal.schedule.a_schedule_exists", new=AsyncMock(return_value=False)),
        patch("posthog.temporal.schedule.a_create_schedule", new=fake_create_schedule),
    ):
        await create_schedule_fn(MagicMock())

    assert captured["schedule_id"] == schedule_id

    # Pull the args out of the schedule action — Temporal stores positional
    # args as a list; the workflow input lives at index 0.
    action = captured["schedule"].action
    raw_input = action.args[0]
    assert isinstance(raw_input, dict), f"input must be a JSON-serializable dict, got {type(raw_input).__name__}"

    # The whole point: this should round-trip through json without exploding.
    encoded = json.dumps(raw_input)
    decoded = json.loads(encoded)
    assert decoded == raw_input

    # And the workflow input model must accept the dict back.
    from posthog.temporal.usage_report.types import RunUsageReportsInputs

    revived = RunUsageReportsInputs(**decoded)
    assert revived.organization_ids is None
    assert revived.day_offset == expected_day_offset


@pytest.mark.asyncio
async def test_finalizer_schedule_retries_until_the_day_is_captured() -> None:
    """The finalizer has no later slot to supersede a failed run — a single
    attempt would silently leave yesterday incomplete (the bug the finalizer
    exists to prevent). Its schedule action must keep retrying across a good
    part of the day, not give up minutes after 03:00.
    """
    captured: dict = {}

    async def fake_create_schedule(client, schedule_id, schedule, trigger_immediately=False):
        captured["schedule"] = schedule

    with (
        patch("posthog.temporal.schedule.a_schedule_exists", new=AsyncMock(return_value=False)),
        patch("posthog.temporal.schedule.a_create_schedule", new=fake_create_schedule),
    ):
        await create_finalize_usage_reports_schedule(MagicMock())

    retry_policy = captured["schedule"].action.retry_policy
    assert retry_policy is not None
    # Lower bounds, not exact values, so tuning the policy doesn't break the
    # test — but a token retry (2 quick attempts) or an uncapped-backoff
    # misconfig can't sneak through either.
    assert retry_policy.maximum_attempts >= 5
    assert retry_policy.maximum_interval is not None
    assert retry_policy.maximum_interval >= timedelta(hours=1)
