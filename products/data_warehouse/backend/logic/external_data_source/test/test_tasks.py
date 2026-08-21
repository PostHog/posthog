from collections import Counter
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from unittest.mock import call, patch

from posthog.redis import get_client

from products.data_warehouse.backend.tasks import (
    reconcile_all_managed_warehouse_tables_task,
    reconcile_managed_warehouse_tables_task,
    reconcile_managed_warehouse_tables_wave_task,
    schedule_managed_warehouse_tables_reconcile,
    send_external_data_failure_digest_catchup,
    send_external_data_failure_digest_task,
)


class TestExternalDataFailureDigestTasks:
    def test_digest_task_builds_digest(self):
        with patch("products.data_warehouse.backend.tasks.tasks.notify_external_data_sync_failures") as mock_notify:
            send_external_data_failure_digest_task(123)

        mock_notify.assert_called_once_with(123)

    def test_digest_task_skips_when_another_send_is_in_flight(self):
        lock = get_client().lock("external_data_failure_digest:123", timeout=10)
        assert lock.acquire(blocking=False)
        try:
            with patch("products.data_warehouse.backend.tasks.tasks.notify_external_data_sync_failures") as mock_notify:
                send_external_data_failure_digest_task(123)
        finally:
            lock.release()

        mock_notify.assert_not_called()

    def test_catchup_fans_out_per_team(self):
        with (
            patch(
                "products.data_warehouse.backend.tasks.tasks.get_team_ids_with_recent_sync_failures",
                return_value=[1, 2],
            ),
            patch("products.data_warehouse.backend.tasks.tasks.send_external_data_failure_digest_task") as mock_task,
        ):
            send_external_data_failure_digest_catchup()

        assert [c.args for c in mock_task.delay.call_args_list] == [(1,), (2,)]


class TestManagedWarehouseTasks:
    def test_reconcile_task_discovers_tables(self) -> None:
        with patch("products.data_warehouse.backend.tasks.tasks.reconcile_managed_warehouse_tables") as mock_reconcile:
            reconcile_managed_warehouse_tables_task(123, "organization-id")

        mock_reconcile.assert_called_once_with(team_id=123, organization_id="organization-id")

    def test_reconcile_task_skips_when_another_reconcile_is_in_flight(self) -> None:
        lock = get_client().lock("managed_warehouse_reconcile:123", timeout=10)
        assert lock.acquire(blocking=False)
        try:
            with patch(
                "products.data_warehouse.backend.tasks.tasks.reconcile_managed_warehouse_tables"
            ) as mock_reconcile:
                reconcile_managed_warehouse_tables_task(123, "organization-id")
        finally:
            lock.release()

        mock_reconcile.assert_not_called()

    def test_reconcile_scheduler_coalesces_repeated_scene_loads(self) -> None:
        schedule_key = "managed_warehouse_reconcile_scheduled:456"
        get_client().delete(schedule_key)
        try:
            with patch(
                "products.data_warehouse.backend.tasks.tasks.reconcile_managed_warehouse_tables_task.delay"
            ) as mock_delay:
                schedule_managed_warehouse_tables_reconcile(team_id=456, organization_id="organization-id")
                schedule_managed_warehouse_tables_reconcile(team_id=456, organization_id="organization-id")
        finally:
            get_client().delete(schedule_key)

        mock_delay.assert_called_once_with(team_id=456, organization_id="organization-id")

    def test_periodic_sweep_evenly_staggers_reconciliations_in_stable_order(self) -> None:
        sweep_started_at = datetime(2026, 1, 1, tzinfo=UTC)
        rows = [
            SimpleNamespace(team_id=4, organization_id="org-b"),
            SimpleNamespace(team_id=3, organization_id="org-a"),
            SimpleNamespace(team_id=2, organization_id="org-b"),
            SimpleNamespace(team_id=1, organization_id="org-a"),
        ]

        with (
            patch(
                "products.data_warehouse.backend.tasks.tasks.list_enabled_backfill_team_memberships",
                return_value=rows,
            ),
            patch(
                "products.data_warehouse.backend.tasks.tasks.reconcile_managed_warehouse_tables_wave_task.apply_async"
            ) as apply_async,
            patch(
                "products.data_warehouse.backend.tasks.tasks.reconcile_managed_warehouse_tables_task.apply_async"
            ) as reconcile_apply_async,
            patch("products.data_warehouse.backend.tasks.tasks.datetime") as mock_datetime,
        ):
            mock_datetime.now.return_value = sweep_started_at
            reconcile_all_managed_warehouse_tables_task()

        reconcile_apply_async.assert_not_called()
        assert apply_async.call_args_list == [
            call(
                kwargs={
                    "items": [{"team_id": 1, "organization_id": "org-a", "countdown": 0}],
                    "wave_due_at": sweep_started_at.isoformat(),
                },
                countdown=0,
                expires=sweep_started_at + timedelta(seconds=300),
            ),
            call(
                kwargs={
                    "items": [{"team_id": 3, "organization_id": "org-a", "countdown": 30}],
                    "wave_due_at": (sweep_started_at + timedelta(seconds=420)).isoformat(),
                },
                countdown=420,
                expires=sweep_started_at + timedelta(seconds=720),
            ),
            call(
                kwargs={
                    "items": [{"team_id": 2, "organization_id": "org-b", "countdown": 0}],
                    "wave_due_at": (sweep_started_at + timedelta(seconds=900)).isoformat(),
                },
                countdown=900,
                expires=sweep_started_at + timedelta(seconds=1200),
            ),
            call(
                kwargs={
                    "items": [{"team_id": 4, "organization_id": "org-b", "countdown": 30}],
                    "wave_due_at": (sweep_started_at + timedelta(seconds=1320)).isoformat(),
                },
                countdown=1320,
                expires=sweep_started_at + timedelta(seconds=1620),
            ),
        ]

    def test_periodic_sweep_stays_even_with_more_memberships_than_seconds(self) -> None:
        rows = [SimpleNamespace(team_id=team_id, organization_id="org") for team_id in range(1801)]

        with (
            patch(
                "products.data_warehouse.backend.tasks.tasks.list_enabled_backfill_team_memberships",
                return_value=rows,
            ),
            patch(
                "products.data_warehouse.backend.tasks.tasks.reconcile_managed_warehouse_tables_wave_task.apply_async"
            ) as apply_async,
            patch(
                "products.data_warehouse.backend.tasks.tasks.reconcile_managed_warehouse_tables_task.apply_async"
            ) as reconcile_apply_async,
        ):
            reconcile_all_managed_warehouse_tables_task()

        reconcile_apply_async.assert_not_called()
        assert apply_async.call_count == 30
        countdowns = [
            task_call.kwargs["countdown"] + item["countdown"]
            for task_call in apply_async.call_args_list
            for item in task_call.kwargs["kwargs"]["items"]
        ]
        assert countdowns[0] == 0
        assert countdowns[-1] == 1799
        assert set(Counter(countdowns).values()) == {1, 2}
        assert (
            max(
                item["countdown"]
                for task_call in apply_async.call_args_list
                for item in task_call.kwargs["kwargs"]["items"]
            )
            == 59
        )

    def test_periodic_wave_enqueues_reconciliations_with_post_due_expiry(self) -> None:
        wave_due_at = datetime.now(UTC) + timedelta(minutes=1)
        items = [
            {"team_id": 1, "organization_id": "org-a", "countdown": 0},
            {"team_id": 2, "organization_id": "org-b", "countdown": 59},
        ]

        with patch(
            "products.data_warehouse.backend.tasks.tasks.reconcile_managed_warehouse_tables_task.apply_async"
        ) as apply_async:
            reconcile_managed_warehouse_tables_wave_task(items, wave_due_at.isoformat())

        assert apply_async.call_args_list == [
            call(
                kwargs={"team_id": 1, "organization_id": "org-a"},
                eta=wave_due_at,
                expires=wave_due_at + timedelta(seconds=300),
            ),
            call(
                kwargs={"team_id": 2, "organization_id": "org-b"},
                eta=wave_due_at + timedelta(seconds=59),
                expires=wave_due_at + timedelta(seconds=359),
            ),
        ]

    def test_periodic_wave_drops_elapsed_slots_instead_of_catching_up(self) -> None:
        wave_due_at = datetime.now(UTC) - timedelta(seconds=30)
        with patch(
            "products.data_warehouse.backend.tasks.tasks.reconcile_managed_warehouse_tables_task.apply_async"
        ) as apply_async:
            reconcile_managed_warehouse_tables_wave_task(
                [
                    {"team_id": 1, "organization_id": "org-a", "countdown": 0},
                    {"team_id": 2, "organization_id": "org-b", "countdown": 59},
                ],
                wave_due_at.isoformat(),
            )

        apply_async.assert_called_once_with(
            kwargs={"team_id": 2, "organization_id": "org-b"},
            eta=wave_due_at + timedelta(seconds=59),
            expires=wave_due_at + timedelta(seconds=359),
        )

    @pytest.mark.parametrize("memberships", [None, []])
    def test_periodic_sweep_schedules_nothing_without_memberships(self, memberships: list[object] | None) -> None:
        with (
            patch(
                "products.data_warehouse.backend.tasks.tasks.list_enabled_backfill_team_memberships",
                return_value=memberships,
            ),
            patch(
                "products.data_warehouse.backend.tasks.tasks.reconcile_managed_warehouse_tables_wave_task.apply_async"
            ) as apply_async,
        ):
            reconcile_all_managed_warehouse_tables_task()

        apply_async.assert_not_called()
