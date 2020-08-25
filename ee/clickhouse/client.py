from clickhouse_driver import Client

from ee.clickhouse.clickhouse_test_runner import TEST_DB
from posthog.settings import TEST

ch_client = Client(host="localhost", database=TEST_DB if TEST else "default")
