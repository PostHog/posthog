from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.schema import EventsNode, FunnelConversionWindowTimeUnit, FunnelsFilter, FunnelsQuery

from posthog.hogql_queries.insights.funnels.funnel import FunnelUDF
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext


class TestFunnelConversionWindow(ClickhouseTestMixin, APIBaseTest):
    def _context(self, funnels_filter: FunnelsFilter) -> FunnelQueryContext:
        query = FunnelsQuery(
            series=[EventsNode(event="step one"), EventsNode(event="step two")],
            funnelsFilter=funnels_filter,
        )
        return FunnelQueryContext(query, self.team)

    @parameterized.expand(
        [
            ("none", None, 14),
            ("zero", 0, 14),
            ("negative", -1, 14),
            ("positive", 7, 7),
        ]
    )
    def test_window_interval_falls_back_for_non_positive(self, _name, configured, expected):
        context = self._context(FunnelsFilter(funnelWindowInterval=configured))
        self.assertEqual(context.funnelWindowInterval, expected)

    @parameterized.expand(
        [
            ("negative_seconds", -1, FunnelConversionWindowTimeUnit.SECOND),
            ("negative_days", -3, FunnelConversionWindowTimeUnit.DAY),
        ]
    )
    def test_conversion_window_limit_is_never_negative(self, _name, configured, unit):
        # A negative conversion window otherwise reaches the funnel UDF as a literal UInt64 argument,
        # which ClickHouse rejects with "The value -1 is not representable as UInt64".
        context = self._context(FunnelsFilter(funnelWindowInterval=configured, funnelWindowIntervalUnit=unit))
        self.assertGreaterEqual(FunnelUDF(context=context).conversion_window_limit(), 0)
