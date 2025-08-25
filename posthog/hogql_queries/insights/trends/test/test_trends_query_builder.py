from datetime import datetime

from freezegun import freeze_time
from posthog.test.base import BaseTest, _create_event, _create_person

from posthog.schema import (
    BaseMathType,
    BreakdownFilter,
    BreakdownType,
    ChartDisplayType,
    DataWarehouseNode,
    DateRange,
    EventsNode,
    HogQLQueryResponse,
    TrendsFilter,
    TrendsQuery,
)

from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings

from posthog.hogql_queries.insights.trends.trends_query_builder import TrendsQueryBuilder
from posthog.hogql_queries.utils.query_date_range import QueryDateRange


class TestTrendsQueryBuilder(BaseTest):
    def setUp(self):
        super().setUp()

        with freeze_time("2023-02-01"):
            _create_person(
                distinct_ids=["some_id"],
                team_id=self.team.pk,
                properties={"$some_prop": "something", "$another_prop": "something"},
            )
            _create_event(
                event="$pageview",
                team=self.team,
                distinct_id="some_id",
                properties={"$geoip_country_code": "AU"},
            )

    def get_response(self, trends_query: TrendsQuery) -> HogQLQueryResponse:
        query_date_range = QueryDateRange(
            date_range=trends_query.dateRange,
            team=self.team,
            interval=trends_query.interval,
            now=datetime.now(),
        )

        timings = HogQLTimings()
        modifiers = create_default_modifiers_for_team(self.team)

        if isinstance(trends_query.series[0], DataWarehouseNode):
            raise Exception("Data Warehouse queries are not supported in this test")

        query_builder = TrendsQueryBuilder(
            trends_query=trends_query,
            team=self.team,
            query_date_range=query_date_range,
            series=trends_query.series[0],
            timings=timings,
            modifiers=modifiers,
        )

        query = query_builder.build_query()

        return execute_hogql_query(
            query_type="TrendsQuery",
            query=query,
            team=self.team,
            timings=timings,
        )

    def test_column_names(self):
        trends_query = TrendsQuery(
            kind="TrendsQuery",
            dateRange=DateRange(date_from="2023-01-01"),
            series=[EventsNode(event="$pageview", math=BaseMathType.TOTAL)],
        )

        response = self.get_response(trends_query)

        assert response.columns is not None
        assert set(response.columns).issubset({"date", "total", "breakdown_value"})

    def assert_column_names_with_display_type(self, display_type: ChartDisplayType):
        trends_query = TrendsQuery(
            kind="TrendsQuery",
            dateRange=DateRange(date_from="2023-01-01"),
            series=[EventsNode(event="$pageview")],
            trendsFilter=TrendsFilter(display=display_type),
        )

        response = self.get_response(trends_query)

        assert response.columns is not None
        assert set(response.columns).issubset({"date", "total", "breakdown_value"})

    def assert_column_names_with_display_type_and_breakdowns(self, display_type: ChartDisplayType):
        trends_query = TrendsQuery(
            kind="TrendsQuery",
            dateRange=DateRange(date_from="2023-01-01"),
            series=[EventsNode(event="$pageview")],
            trendsFilter=TrendsFilter(display=display_type),
            breakdownFilter=BreakdownFilter(breakdown="$geoip_country_code", breakdown_type=BreakdownType.EVENT),
        )

        response = self.get_response(trends_query)

        assert response.columns is not None
        assert set(response.columns).issubset({"date", "total", "breakdown_value"})

    def test_column_names_with_display_type(self):
        self.assert_column_names_with_display_type(ChartDisplayType.ACTIONS_AREA_GRAPH)
        self.assert_column_names_with_display_type(ChartDisplayType.ACTIONS_BAR)
        self.assert_column_names_with_display_type(ChartDisplayType.ACTIONS_BAR_VALUE)
        self.assert_column_names_with_display_type(ChartDisplayType.ACTIONS_LINE_GRAPH)
        self.assert_column_names_with_display_type(ChartDisplayType.ACTIONS_PIE)
        self.assert_column_names_with_display_type(ChartDisplayType.BOLD_NUMBER)
        self.assert_column_names_with_display_type(ChartDisplayType.WORLD_MAP)
        self.assert_column_names_with_display_type(ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE)

    def test_column_names_with_display_type_and_breakdowns(self):
        self.assert_column_names_with_display_type_and_breakdowns(ChartDisplayType.ACTIONS_AREA_GRAPH)
        self.assert_column_names_with_display_type_and_breakdowns(ChartDisplayType.ACTIONS_BAR)
        self.assert_column_names_with_display_type_and_breakdowns(ChartDisplayType.ACTIONS_BAR_VALUE)
        self.assert_column_names_with_display_type_and_breakdowns(ChartDisplayType.ACTIONS_LINE_GRAPH)
        self.assert_column_names_with_display_type_and_breakdowns(ChartDisplayType.ACTIONS_PIE)
        self.assert_column_names_with_display_type_and_breakdowns(ChartDisplayType.WORLD_MAP)
        self.assert_column_names_with_display_type_and_breakdowns(ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE)
