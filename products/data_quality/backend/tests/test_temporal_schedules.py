from collections.abc import Callable
from datetime import timedelta
from uuid import UUID

from unittest.mock import AsyncMock, Mock

from django.test import SimpleTestCase

from temporalio.client import (
    ScheduleAlreadyRunningError,
    ScheduleDescription,
    ScheduleOverlapPolicy,
    ScheduleUpdate,
    ScheduleUpdateInput,
)

from products.data_quality.backend.logic.metric_schedules import MetricScheduleKey, MetricSchedules


class TestTemporalMetricSchedules(SimpleTestCase):
    def setUp(self) -> None:
        self.key = MetricScheduleKey(team_id=123, metric_id=UUID("00000000-0000-0000-0000-000000000001"))
        self.temporal = Mock()
        self.temporal.create_schedule = AsyncMock()
        self.handle = Mock(describe=AsyncMock(), update=AsyncMock())
        self.temporal.get_schedule_handle.return_value = self.handle
        self.schedules = MetricSchedules(self.temporal)

    async def test_creation_uses_native_cadence_and_execution_policies(self) -> None:
        await self.schedules.ensure(self.key)
        schedule = self.temporal.create_schedule.call_args.kwargs["schedule"]
        assert schedule.spec.intervals[0].every == timedelta(days=1)
        assert schedule.spec.intervals[0].offset < timedelta(days=1)
        assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
        assert schedule.policy.catchup_window == timedelta(minutes=15)
        assert not schedule.policy.pause_on_failure
        assert self.temporal.create_schedule.call_args.kwargs["trigger_immediately"]
        assert schedule.action.args[0].metric_ids == [str(self.key.metric_id)]
        assert schedule.action.args[0].team_id == self.key.team_id

    async def test_repeated_creation_preserves_temporal_configuration(self) -> None:
        self.temporal.create_schedule.side_effect = ScheduleAlreadyRunningError()
        await self.schedules.ensure(self.key)
        self.handle.update.assert_not_called()

    async def test_interval_update_preserves_a_concurrent_pause(self) -> None:
        current = self.schedules.build(self.key)
        current.state.paused = True
        current.state.note = "Maintenance"
        current.spec.jitter = timedelta(seconds=30)
        self.handle.describe.return_value = Mock(spec=ScheduleDescription, schedule=current)

        async def update(callback: Callable[[ScheduleUpdateInput], ScheduleUpdate]) -> None:
            result = callback(ScheduleUpdateInput(description=Mock(spec=ScheduleDescription, schedule=current)))
            assert result.schedule.state.paused
            assert result.schedule.state.note == "Maintenance"
            assert result.schedule.spec.jitter == timedelta(seconds=30)
            assert result.schedule.spec.intervals[0].every == timedelta(hours=6)

        self.handle.update.side_effect = update
        await self.schedules.update(self.key, interval="6hour")

    async def test_pause_update_preserves_existing_interval(self) -> None:
        current = self.schedules.build(self.key, interval="6hour")

        async def update(callback: Callable[[ScheduleUpdateInput], ScheduleUpdate]) -> None:
            result = callback(ScheduleUpdateInput(description=Mock(spec=ScheduleDescription, schedule=current)))
            assert result.schedule.state.paused
            assert result.schedule.spec.intervals[0].every == timedelta(hours=6)

        self.handle.update.side_effect = update
        await self.schedules.update(self.key, enabled=False)
