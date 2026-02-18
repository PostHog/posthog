from datetime import datetime

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import BreakdownFilter, BreakdownType, DateRange, EventsNode, TrendsQuery

from posthog.hogql import ast
from posthog.hogql.constants import BREAKDOWN_VALUE_MAX_LENGTH, MAX_BREAKDOWN_VALUES_LIMIT
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.timings import HogQLTimings

from posthog.hogql_queries.insights.trends.breakdown import Breakdown
from posthog.hogql_queries.insights.trends.trends_query_builder import TrendsQueryBuilder
from posthog.hogql_queries.utils.query_date_range import QueryDateRange


class TestBreakdownLimitCap(BaseTest):
    def _build_query_builder(self, trends_query: TrendsQuery) -> TrendsQueryBuilder:
        query_date_range = QueryDateRange(
            date_range=trends_query.dateRange,
            team=self.team,
            interval=trends_query.interval,
            now=datetime.now(),
        )
        return TrendsQueryBuilder(
            trends_query=trends_query,
            team=self.team,
            query_date_range=query_date_range,
            series=trends_query.series[0],
            timings=HogQLTimings(),
            modifiers=create_default_modifiers_for_team(self.team),
        )

    @parameterized.expand(
        [
            ("no_limit_set", None, 25),
            ("below_cap", 50, 50),
            ("at_cap", MAX_BREAKDOWN_VALUES_LIMIT, MAX_BREAKDOWN_VALUES_LIMIT),
            ("above_cap", 1000, MAX_BREAKDOWN_VALUES_LIMIT),
        ]
    )
    def test_get_breakdown_limit_caps_at_max(self, _name: str, breakdown_limit: int | None, expected: int):
        trends_query = TrendsQuery(
            kind="TrendsQuery",
            dateRange=DateRange(date_from="2023-01-01"),
            series=[EventsNode(event="$pageview")],
            breakdownFilter=BreakdownFilter(
                breakdown="$browser",
                breakdown_type=BreakdownType.EVENT,
                breakdown_limit=breakdown_limit,
            ),
        )
        builder = self._build_query_builder(trends_query)
        assert builder._get_breakdown_limit() == expected


class TestBreakdownValueTruncation(BaseTest):
    def test_replace_null_values_transform_includes_left_truncation(self):
        node = ast.Field(chain=["properties", "$browser"])
        result = Breakdown.get_replace_null_values_transform(node)

        # The outermost call is ifNull(nullIf(left(toString(...), N), ''), nil)
        # Verify the AST contains a `left` call wrapping `toString`
        assert isinstance(result, ast.Call)
        assert result.name == "ifNull"
        null_if_call = result.args[0]
        assert isinstance(null_if_call, ast.Call)
        assert null_if_call.name == "nullIf"
        left_call = null_if_call.args[0]
        assert isinstance(left_call, ast.Call)
        assert left_call.name == "left"
        to_string_call = left_call.args[0]
        assert isinstance(to_string_call, ast.Call)
        assert to_string_call.name == "toString"
        max_length = left_call.args[1]
        assert isinstance(max_length, ast.Constant)
        assert max_length.value == BREAKDOWN_VALUE_MAX_LENGTH
