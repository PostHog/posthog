from posthog.clickhouse.client import sync_execute
from posthog.models.performance.sql import insert_single_network_performance_event
from posthog.test.base import ClickhouseTestMixin, ClickhouseDestroyTablesMixin, BaseTest


class TestNetworkPerformanceTable(ClickhouseTestMixin, ClickhouseDestroyTablesMixin, BaseTest):
    def test_can_write_a_single_network_performance_event(self) -> None:
        insert_single_network_performance_event()
        result = sync_execute("select * from performance_events")
        assert result == {}

    def test_transfer_size_can_be_empty(self) -> None:
        pass
