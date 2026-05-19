"""Regression tests for `create_run_usage_reports_schedule`.

The previous version of this code passed `dataclasses.asdict(...)` on
`RunUsageReportsInputs` *after* it was migrated to pydantic — that
silently raised `TypeError` the first time the worker registered the
schedule, and *no* test caught it because nothing in the suite ever
imported and called the schedule-creation function.

These tests close that gap: they actually invoke the function with a
mocked client and assert it (a) doesn't raise and (b) hands Temporal a
JSON-serializable input.
"""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_create_run_usage_reports_schedule_does_not_raise() -> None:
    """The schedule-builder must not blow up when called — covers both the
    `a_schedule_exists is False` (create) and `True` (update) branches.
    """
    from posthog.temporal.schedule import create_run_usage_reports_schedule

    client = MagicMock()

    # First-time registration: schedule doesn't exist → `a_create_schedule` runs.
    with (
        patch("posthog.temporal.schedule.a_schedule_exists", new=AsyncMock(return_value=False)),
        patch("posthog.temporal.schedule.a_create_schedule", new=AsyncMock()) as create_mock,
        patch("posthog.temporal.schedule.a_update_schedule", new=AsyncMock()) as update_mock,
    ):
        await create_run_usage_reports_schedule(client)
        create_mock.assert_awaited_once()
        update_mock.assert_not_awaited()

    # Re-registration: schedule already exists → `a_update_schedule` runs.
    with (
        patch("posthog.temporal.schedule.a_schedule_exists", new=AsyncMock(return_value=True)),
        patch("posthog.temporal.schedule.a_create_schedule", new=AsyncMock()) as create_mock,
        patch("posthog.temporal.schedule.a_update_schedule", new=AsyncMock()) as update_mock,
    ):
        await create_run_usage_reports_schedule(client)
        update_mock.assert_awaited_once()
        create_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_usage_reports_schedule_input_is_json_serializable() -> None:
    """Temporal serializes the `ScheduleActionStartWorkflow` input via the
    data converter. Even with the pydantic data converter, JSON-encoding
    must round-trip — otherwise registration fails the moment it hits
    the wire. Catches the original `dataclasses.asdict(pydantic_model)`
    bug that landed on this branch.
    """
    from posthog.temporal.schedule import create_run_usage_reports_schedule

    captured: dict = {}

    async def fake_create_schedule(client, schedule_id, schedule, trigger_immediately=False):
        captured["schedule_id"] = schedule_id
        captured["schedule"] = schedule

    with (
        patch("posthog.temporal.schedule.a_schedule_exists", new=AsyncMock(return_value=False)),
        patch("posthog.temporal.schedule.a_create_schedule", new=fake_create_schedule),
    ):
        await create_run_usage_reports_schedule(MagicMock())

    assert captured["schedule_id"] == "run-usage-reports-schedule"

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
    assert revived.at is None
