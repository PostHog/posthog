from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import get_client_from_pool
from posthog.test.clickhouse_free import ClickhouseFreeSimpleTestCase


class TestClickhouseFreeSimpleTestCase(ClickhouseFreeSimpleTestCase):
    def test_rejects_clickhouse_queries(self) -> None:
        with self.assertRaisesRegex(AssertionError, "ClickHouse access is not allowed"):
            sync_execute("SELECT 1", flush=False)

        with self.assertRaisesRegex(AssertionError, "ClickHouse access is not allowed"):
            get_client_from_pool()
