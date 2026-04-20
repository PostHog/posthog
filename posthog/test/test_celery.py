from unittest import TestCase
from unittest.mock import Mock, patch

from celery import states as celery_states

from posthog.celery import PROCESS_QUERY_TASK_NAME, _mark_process_query_task_failed_from_signal
from posthog.tasks.tasks import clickhouse_errors_count


class TestCeleryMetrics(TestCase):
    @patch("posthog.clickhouse.client.sync_execute")
    @patch("posthog.metrics.push_to_gateway")
    @patch("django.conf.settings.PROM_PUSHGATEWAY_ADDRESS", value="127.0.0.1")
    def test_clickhouse_errors_count(self, _, mock_push_to_gateway, mock_sync_execute):
        mock_sync_execute.return_value = [["ch1", "1", "NO_ZOOKEEPER", 123, 60]]
        clickhouse_errors_count()
        self.assertEqual(1, mock_push_to_gateway.call_count)
        registry = mock_push_to_gateway.call_args[1]["registry"]
        self.assertEqual(
            60,
            registry.get_sample_value(
                "posthog_celery_clickhouse_errors",
                labels={"name": "NO_ZOOKEEPER", "replica": "ch1", "shard": "1"},
            ),
        )

    @patch("posthog.clickhouse.client.execute_async.mark_process_query_task_failed")
    def test_process_query_task_failure_signal_marks_query_failed(self, mark_process_query_task_failed_mock):
        sender = Mock()
        sender.name = PROCESS_QUERY_TASK_NAME

        _mark_process_query_task_failed_from_signal(
            sender,
            {"task_id": "celery-task-id", "args": (123, None, "query-id"), "exception": RuntimeError("boom")},
            state=celery_states.FAILURE,
        )

        mark_process_query_task_failed_mock.assert_called_once()
        self.assertEqual(mark_process_query_task_failed_mock.call_args.kwargs["team_id"], 123)
        self.assertEqual(mark_process_query_task_failed_mock.call_args.kwargs["query_id"], "query-id")
        self.assertEqual(mark_process_query_task_failed_mock.call_args.kwargs["task_id"], "celery-task-id")
        self.assertEqual(mark_process_query_task_failed_mock.call_args.kwargs["state"], celery_states.FAILURE)
