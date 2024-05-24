from unittest.mock import patch

from django.test import SimpleTestCase

from posthog.tasks.poll_query_performance import query_manager_from_initial_query_id, poll_query_performance


class TestPollQueryPerformance(SimpleTestCase):
    def test_query_manager_from_initial_query_id_succeeds(self):
        self.assertIsNotNone(query_manager_from_initial_query_id("1_00008400-e29b-41d4-a716-446655440000_fwefwef"))
        self.assertIsNotNone(query_manager_from_initial_query_id("123123_550e8400-e29b-41d4-a716-446655440000_fwefwef"))

    def test_query_manager_from_initial_query_id_fails(self):
        self.assertIsNone(query_manager_from_initial_query_id("550e8400-e29b-41d4-a716-446655440000"))
        self.assertIsNone(query_manager_from_initial_query_id("fewf_550e8400-e29b-41d4-a716-446655440000_fwefwef"))
        self.assertIsNone(query_manager_from_initial_query_id("1a_550e8400-e29b-41d4-a716-446655440000_fwefwef"))

    @patch("posthog.tasks.poll_query_performance.QueryStatusManager")
    @patch("posthog.tasks.poll_query_performance.sync_execute")
    def test_writes_to_redis_correctly(self, mock_sync_execute, mock_QueryStatusManager):
        bytes_read = 111
        rows_read = 222
        total_rows_approx = 333
        time_elapsed = 4.301284
        millisecond_cpu_time = 3321332424
        mock_sync_execute.return_value = [
            ("None_None_tHrh4Ox9", 0, 0, 0, 0.002112, 0),
            (
                "12345_550e8400-e29b-41d4-a716-446655440000_eO290UUI",
                rows_read,
                bytes_read,
                total_rows_approx,
                time_elapsed,
                millisecond_cpu_time,
            ),
        ]
        mock_manager = mock_QueryStatusManager.return_value

        poll_query_performance()

        mock_sync_execute.assert_called_once()
        mock_QueryStatusManager.assert_called_once_with("550e8400-e29b-41d4-a716-446655440000", "12345")
        mock_manager.update_clickhouse_query_progress.assert_called_once_with(
            "12345_550e8400-e29b-41d4-a716-446655440000_eO290UUI",
            {
                "bytes_read": bytes_read,
                "rows_read": rows_read,
                "estimated_rows_total": total_rows_approx,
                "time_elapsed": int(time_elapsed),
                "active_cpu_time": millisecond_cpu_time,
            },
        )
