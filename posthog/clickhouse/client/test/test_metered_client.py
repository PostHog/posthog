from types import SimpleNamespace

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import SimpleTestCase

from clickhouse_driver import Client
from parameterized import parameterized

from posthog.clickhouse.client.connection import get_client_from_pool
from posthog.clickhouse.client.metered_client import MeteredChPool, MeteredClient, cpu_microseconds_from_profile_events

PROFILE_EVENTS_COLUMNS = [("host_name", "String"), ("type", "String"), ("name", "String"), ("value", "Int64")]


class TestCpuMicrosecondsFromProfileEvents(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "increments_across_hosts_only",
                PROFILE_EVENTS_COLUMNS,
                [
                    ("initiator", "increment", "OSCPUVirtualTimeMicroseconds", 1000),
                    ("shard-1", "increment", "OSCPUVirtualTimeMicroseconds", 2500),
                    ("shard-1", "gauge", "OSCPUVirtualTimeMicroseconds", 999999),
                    ("shard-1", "increment", "SelectedRows", 42),
                ],
                3500,
            ),
            ("unexpected_columns", [("host_name", "String")], [("initiator",)], 0),
        ]
    )
    def test_sums_cpu(self, _name, columns, rows, expected):
        block = SimpleNamespace(columns_with_types=columns, get_rows=lambda: rows)
        assert cpu_microseconds_from_profile_events(block) == expected


class TestMeteredClient(ClickhouseTestMixin, BaseTest):
    def test_pool_clients_report_cpu_per_query(self):
        with get_client_from_pool() as client:
            assert isinstance(client, MeteredClient)
            client.execute("SELECT sum(cityHash64(number)) FROM (SELECT number FROM system.numbers LIMIT 2000000)")
            heavy = client.last_query.cpu_microseconds
            client.execute("SELECT 1")
            assert heavy > 0
            assert client.last_query.cpu_microseconds < heavy

    def test_query_killed_by_the_server_keeps_its_progress_and_cpu(self):
        with get_client_from_pool() as client:
            try:
                client.execute(
                    "SELECT sum(cityHash64(number)) FROM numbers_mt(3000000000)",
                    settings={"max_execution_time": 1, "max_threads": 2},
                )
            except Exception:
                pass
            assert client.last_query is None
            assert client.last_failed_query.progress.bytes > 0
            assert client.last_failed_query.cpu_microseconds > 0
            client.execute("SELECT 1")
            assert client.last_failed_query is None

    def test_pool_hands_out_plain_clients_when_the_setting_is_off(self):
        with patch("posthog.clickhouse.client.metered_client.metered_client_enabled", return_value=False):
            pool = MeteredChPool(host="localhost", port=1, connections_min=1, connections_max=1)
            client = pool.pull()
        assert type(client) is Client
        pool.push(client)
