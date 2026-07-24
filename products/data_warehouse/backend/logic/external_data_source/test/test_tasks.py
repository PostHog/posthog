from unittest.mock import patch

from posthog.redis import get_client

from products.data_warehouse.backend.tasks import (
    reconcile_managed_warehouse_tables_task,
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
