import asyncio
from types import SimpleNamespace
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync, sync_to_async
from parameterized import parameterized
from temporalio.service import RPCError, RPCStatusCode
from temporalio.testing import ActivityEnvironment

from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.data_catalog.backend.facade.api import upsert_metric
from products.data_quality.backend.facade.enums import SuiteRunTrigger
from products.data_quality.backend.logic.checks import upsert_check
from products.data_quality.backend.logic.metric_schedules import MetricScheduleKey, MetricSchedules
from products.data_quality.backend.logic.schedules import (
    get_schedule,
    provision_metric_schedule,
    schedule_key,
    set_schedule,
)
from products.data_quality.backend.models import DataQualityCheck
from products.data_quality.backend.temporal.activities.prepare_check_suite import prepare_check_suite_activity
from products.data_quality.backend.temporal.activities.reconcile_schedules import (
    RECONCILE_CONCURRENCY_LIMIT,
    ScheduleReconcileCursor,
    _check_page,
    _dead_schedules,
    reconcile_metric_schedules_activity,
)
from products.data_quality.backend.temporal.contracts import PreparedSuite, RunCheckSuiteInputs

from .schedule_helpers import schedule_client


class TestSchedules(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(team_scope(self.team.id))
        self.metric = upsert_metric(
            team=self.team,
            user=self.user,
            name="revenue",
            description="Revenue",
            definition={"kind": "HogQLQuery", "query": "SELECT 1 AS amount"},
        )
        self.temporal = schedule_client()
        self.enterContext(
            patch("products.data_quality.backend.logic.schedules.async_connect", AsyncMock(return_value=self.temporal))
        )
        self.key = schedule_key(self.team.id, "metric", self.metric.id)

    def _create(self) -> None:
        upsert_check(
            team=self.team,
            user=self.user,
            subject_type="metric",
            subject_uuid=str(self.metric.id),
            check_type="custom_sql",
            column_name="",
            config={"query": "SELECT * FROM {metric} WHERE amount < 0"},
        )

    def test_check_commit_creates_one_schedule_and_repair_preserves_preferences(self) -> None:
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            self._create()
        self.temporal.create_schedule.assert_not_called()
        for callback in callbacks:
            callback()
        assert len(self.temporal.schedules) == 1
        set_schedule(self.team.id, "metric", self.metric.id, interval="6hour", enabled=False)
        provision_metric_schedule(self.team.id, str(self.metric.id))
        schedule = get_schedule(self.team.id, "metric", self.metric.id)
        assert schedule is not None
        assert schedule.interval == "6hour"
        assert not schedule.enabled
        assert schedule.next_run_at is None
        assert len(self.temporal.schedules) == 1

    def test_failed_provision_is_recoverable_from_committed_checks(self) -> None:
        original_create = self.temporal.create_schedule.side_effect
        self.temporal.create_schedule.side_effect = RPCError("Unavailable", RPCStatusCode.UNAVAILABLE, b"")
        with self.captureOnCommitCallbacks(execute=True):
            self._create()
        assert not self.temporal.schedules
        checks = _check_page(None)
        assert [check.metric_id for check in checks] == [self.metric.id]
        self.temporal.create_schedule.side_effect = original_create
        async_to_sync(MetricSchedules(self.temporal).ensure)(self.key)
        assert get_schedule(self.team.id, "metric", self.metric.id) is not None

    def test_canonical_environment_uses_the_same_schedule(self) -> None:
        child = Team.objects.create(organization=self.organization, name="child", parent_team=self.team)
        assert schedule_key(child.id, "metric", self.metric.id) == self.key
        provision_metric_schedule(self.team.id, str(self.metric.id))
        provision_metric_schedule(child.id, str(self.metric.id))
        assert len(self.temporal.schedules) == 1

    def test_cleanup_preserves_live_subjects_and_does_not_trust_another_team(self) -> None:
        other = Team.objects.create(organization=self.organization)
        other_key = schedule_key(other.id, "metric", self.metric.id)
        assert _dead_schedules([self.key.temporal_id, other_key.temporal_id]) == [other_key.temporal_id]
        self.metric.deleted = True
        self.metric.save(update_fields=["deleted"])
        assert _dead_schedules([self.key.temporal_id]) == [self.key.temporal_id]

    def test_repair_pages_past_deleted_and_disabled_checks(self) -> None:
        self._create()
        check = DataQualityCheck.objects.for_team(self.team.id).get(metric_id=self.metric.id)
        check.enabled = False
        check.deleted = True
        check.save(update_fields=["enabled", "deleted"])
        assert [entry.id for entry in _check_page(None)] == [check.id]
        assert not _check_page(str(check.id))
        self.metric.deleted = True
        self.metric.save(update_fields=["deleted"])
        assert not _check_page(None)

    async def _reconcile(self) -> ScheduleReconcileCursor:
        return await ActivityEnvironment().run(reconcile_metric_schedules_activity, ScheduleReconcileCursor())

    async def _reconcile_checks(self) -> ScheduleReconcileCursor:
        return await ActivityEnvironment().run(reconcile_metric_schedules_activity, ScheduleReconcileCursor())

    def test_reconciliation_recovers_missing_schedules_without_overwriting_pauses(self) -> None:
        self._create()
        with (
            patch(
                "products.data_quality.backend.temporal.activities.reconcile_schedules.async_connect",
                AsyncMock(return_value=self.temporal),
            ),
            patch(
                "products.data_quality.backend.temporal.activities.reconcile_schedules.database_sync_to_async_pool",
                sync_to_async,
            ),
        ):
            cursor = async_to_sync(self._reconcile)()
            assert cursor.cleanup
            set_schedule(self.team.id, "metric", self.metric.id, interval="6hour", enabled=False)
            async_to_sync(self._reconcile)()
        schedule = get_schedule(self.team.id, "metric", self.metric.id)
        assert schedule is not None
        assert not schedule.enabled
        assert schedule.interval == "6hour"

    def test_reconciliation_bounds_overlapping_repairs_and_deduplicates_metric_checks(self) -> None:
        metric_ids = [self.metric.id, self.metric.id, *(uuid4() for _ in range(RECONCILE_CONCURRENCY_LIMIT + 1))]
        checks = [SimpleNamespace(id=uuid4(), team_id=self.team.id, metric_id=metric_id) for metric_id in metric_ids]
        started = asyncio.Event()
        release = asyncio.Event()
        active = 0
        maximum_active = 0

        async def ensure(_key: MetricScheduleKey) -> None:
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            if active == RECONCILE_CONCURRENCY_LIMIT:
                started.set()
            await release.wait()
            active -= 1

        async def page(_after_check_id: str | None) -> list[SimpleNamespace]:
            return checks

        async def run() -> ScheduleReconcileCursor:
            task = asyncio.create_task(self._reconcile_checks())
            await started.wait()
            assert maximum_active == RECONCILE_CONCURRENCY_LIMIT
            release.set()
            return await task

        with (
            patch(
                "products.data_quality.backend.temporal.activities.reconcile_schedules.async_connect",
                AsyncMock(return_value=self.temporal),
            ),
            patch(
                "products.data_quality.backend.temporal.activities.reconcile_schedules.database_sync_to_async_pool",
                return_value=page,
            ),
            patch.object(MetricSchedules, "ensure", AsyncMock(side_effect=ensure)) as mocked_ensure,
        ):
            cursor = async_to_sync(run)()

        assert cursor.after_check_id == str(checks[-1].id)
        assert mocked_ensure.await_count == len(set(metric_ids))
        assert maximum_active == RECONCILE_CONCURRENCY_LIMIT

    def test_reconciliation_bounds_overlapping_deletions(self) -> None:
        schedule_ids = [f"data-quality-metric:{self.team.id}:{uuid4()}" for _ in range(RECONCILE_CONCURRENCY_LIMIT + 1)]
        schedule_page = SimpleNamespace(
            current_page=[SimpleNamespace(id=schedule_id) for schedule_id in schedule_ids],
            next_page_token=None,
            fetch_next_page=AsyncMock(),
        )
        self.temporal.list_schedules = AsyncMock(return_value=schedule_page)
        started = asyncio.Event()
        release = asyncio.Event()
        active = 0
        maximum_active = 0

        async def delete(_client: object, _schedule_id: str) -> None:
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            if active == RECONCILE_CONCURRENCY_LIMIT:
                started.set()
            await release.wait()
            active -= 1

        async def dead(_schedule_ids: list[str]) -> list[str]:
            return schedule_ids

        async def run() -> ScheduleReconcileCursor:
            task = asyncio.create_task(
                ActivityEnvironment().run(
                    reconcile_metric_schedules_activity,
                    ScheduleReconcileCursor(cleanup=True),
                )
            )
            await started.wait()
            assert maximum_active == RECONCILE_CONCURRENCY_LIMIT
            release.set()
            return await task

        with (
            patch(
                "products.data_quality.backend.temporal.activities.reconcile_schedules.async_connect",
                AsyncMock(return_value=self.temporal),
            ),
            patch(
                "products.data_quality.backend.temporal.activities.reconcile_schedules.database_sync_to_async_pool",
                return_value=dead,
            ),
            patch(
                "products.data_quality.backend.temporal.activities.reconcile_schedules.a_delete_schedule",
                AsyncMock(side_effect=delete),
            ) as mocked_delete,
        ):
            cursor = async_to_sync(run)()

        assert cursor.done
        assert mocked_delete.await_count == len(schedule_ids)
        assert maximum_active == RECONCILE_CONCURRENCY_LIMIT

    def test_reconciliation_cancels_failed_page_tasks_and_retries_the_same_cursor(self) -> None:
        metric_ids = [self.metric.id, uuid4(), uuid4()]
        checks = [SimpleNamespace(id=uuid4(), team_id=self.team.id, metric_id=metric_id) for metric_id in metric_ids]
        blocked_task_started = asyncio.Event()
        blocked_task_canceled = asyncio.Event()
        never_release = asyncio.Event()
        completed: list[MetricScheduleKey] = []

        async def fail_after_partial_completion(key: MetricScheduleKey) -> None:
            if key.metric_id == metric_ids[0]:
                completed.append(key)
                return
            if key.metric_id == metric_ids[1]:
                await blocked_task_started.wait()
                raise RuntimeError("Temporal is unavailable")
            blocked_task_started.set()
            try:
                await never_release.wait()
            except asyncio.CancelledError:
                blocked_task_canceled.set()
                raise

        async def page(_after_check_id: str | None) -> list[SimpleNamespace]:
            return checks

        async def retry(key: MetricScheduleKey) -> None:
            completed.append(key)

        with (
            patch(
                "products.data_quality.backend.temporal.activities.reconcile_schedules.async_connect",
                AsyncMock(return_value=self.temporal),
            ),
            patch(
                "products.data_quality.backend.temporal.activities.reconcile_schedules.database_sync_to_async_pool",
                return_value=page,
            ),
            patch.object(
                MetricSchedules, "ensure", AsyncMock(side_effect=fail_after_partial_completion)
            ) as mocked_ensure,
        ):
            with self.assertRaises(ExceptionGroup):
                async_to_sync(self._reconcile_checks)()
            assert blocked_task_canceled.is_set()
            mocked_ensure.side_effect = retry
            cursor = async_to_sync(self._reconcile_checks)()

        assert cursor.after_check_id == str(checks[-1].id)
        assert completed.count(MetricScheduleKey(team_id=self.team.id, metric_id=metric_ids[0])) == 2

    async def _prepare_scheduled(self) -> PreparedSuite:
        return await ActivityEnvironment().run(
            prepare_check_suite_activity,
            RunCheckSuiteInputs(
                team_id=self.team.id,
                trigger=SuiteRunTrigger.SCHEDULED,
                metric_ids=[str(self.metric.id)],
                schedule_id=self.key.temporal_id,
            ),
        )

    @parameterized.expand([("enabled", True, True), ("paused", False, True), ("missing", True, False)])
    def test_scheduled_preparation_checks_temporal_state(self, _name: str, enabled: bool, exists: bool) -> None:
        self._create()
        if exists:
            provision_metric_schedule(self.team.id, str(self.metric.id))
            set_schedule(self.team.id, "metric", self.metric.id, enabled=enabled)
        with (
            patch(
                "products.data_quality.backend.temporal.activities.prepare_check_suite.async_connect",
                AsyncMock(return_value=self.temporal),
            ),
            patch(
                "products.data_quality.backend.temporal.activities.prepare_check_suite.get_data_quality_checks_flag_for_team_id",
                return_value=True,
            ),
        ):
            prepared = async_to_sync(self._prepare_scheduled)()
        assert bool(prepared.batches) == (enabled and exists)
