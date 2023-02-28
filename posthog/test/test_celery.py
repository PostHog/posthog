import unittest
from unittest.mock import patch

from prometheus_client import REGISTRY

from posthog.celery import clickhouse_errors_count


class TestCeleryMetrics(unittest.TestCase):
    @patch("posthog.client.sync_execute")
    def test_clickhouse_errors_count(self, mock_sync_execute):
        mock_sync_execute.return_value = [["ch1", 1, "NO_ZOOKEEPER", 123, 60]]
        clickhouse_errors_count()
        g = REGISTRY.get_sample_value("posthog_celery_clickhouse_errors")
        self.assertEqual(60, g)
