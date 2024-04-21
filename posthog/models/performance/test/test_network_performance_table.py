from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.models.performance.sql import insert_single_network_performance_event
from posthog.test.base import ClickhouseTestMixin, ClickhouseDestroyTablesMixin, BaseTest


class TestNetworkPerformanceTable(ClickhouseTestMixin, ClickhouseDestroyTablesMixin, BaseTest):
    def test_can_write_a_single_network_performance_event(self) -> None:
        insert_single_network_performance_event(team_id=self.team.pk)
        result = sync_execute("select * from performance_events")
        assert len(result) == 1

    @parameterized.expand([[None], [0], [123]])
    def test_transfer_size_can_be_set_as_expected(self, provided_value: int | None) -> None:
        """
        Transfer size uses None and 0 to mean different things in the performance entry spec
        We need to make sure we store None when it is not provided otherwise - if we default to 0 -
        then we're making a statement about caching for that resource that is only true when the
        browser explicitly provides 0
        """
        insert_single_network_performance_event(team_id=self.team.pk, transfer_size=provided_value)
        result = sync_execute("select transfer_size from performance_events")
        assert result[0][0] == provided_value
