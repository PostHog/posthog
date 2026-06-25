from unittest.mock import patch

from posthog.redis import get_client

from products.data_warehouse.backend.tasks import (
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
