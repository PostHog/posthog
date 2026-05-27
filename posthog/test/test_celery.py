from unittest import TestCase
from unittest.mock import patch

from parameterized import parameterized

from posthog.celery import _celery_caller_tag
from posthog.tasks.tasks import clickhouse_errors_count


class TestCeleryCallerTag(TestCase):
    @parameterized.expand(
        [
            ("dotted_task", "posthog.tasks.calculate_cohort.calculate_cohort_ch", "celery/calculate_cohort_ch"),
            ("simple_name", "my_task", "celery/my_task"),
            ("deeply_nested", "a.b.c.d.run", "celery/run"),
        ]
    )
    def test_derives_tag_from_task_name(self, _name: str, task_name: str, expected: str) -> None:
        self.assertEqual(_celery_caller_tag(task_name), expected)


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
