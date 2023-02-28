import unittest

from prometheus_client import REGISTRY

from posthog.celery import clickhouse_errors_count


class TestCeleryMetrics(unittest.TestCase):
    def test_clickhouse_errors_count(self):
        clickhouse_errors_count()
        g = REGISTRY.get_sample_value("celery_clickhouse_errors")
        self.assertEqual(0, g)
