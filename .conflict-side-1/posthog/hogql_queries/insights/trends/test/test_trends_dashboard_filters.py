from typing import Optional

from posthog.test.base import BaseTest

from posthog.schema import (
    ActionsNode,
    BreakdownFilter,
    CompareFilter,
    DashboardFilter,
    DateRange,
    EventPropertyFilter,
    EventsNode,
    FilterLogicalOperator,
    HogQLQueryModifiers,
    IntervalType,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    TrendsFilter,
    TrendsQuery,
)

from posthog.hogql.constants import LimitContext

from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner


class TestTrendsDashboardFilters(BaseTest):
    def _create_query_runner(
        self,
        date_from: str,
        date_to: Optional[str],
        interval: IntervalType,
        series: Optional[list[EventsNode | ActionsNode]],
        properties: Optional[list[EventPropertyFilter] | PropertyGroupFilter] = None,
        trends_filters: Optional[TrendsFilter] = None,
        breakdown: Optional[BreakdownFilter] = None,
        filter_test_accounts: Optional[bool] = None,
        hogql_modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
        explicit_date: Optional[bool] = None,
        compare_filters: Optional[CompareFilter] = None,
    ) -> TrendsQueryRunner:
        query_series: list[EventsNode | ActionsNode] = [EventsNode(event="$pageview")] if series is None else series
        query = TrendsQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to, explicitDate=explicit_date),
            interval=interval,
            series=query_series,
            trendsFilter=trends_filters,
            breakdownFilter=breakdown,
            filterTestAccounts=filter_test_accounts,
            properties=properties,
            compareFilter=compare_filters,
        )
        return TrendsQueryRunner(team=self.team, query=query, modifiers=hogql_modifiers, limit_context=limit_context)

    def test_empty_dashboard_filters_change_nothing(self):
        query_runner = self._create_query_runner(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            None,
        )

        assert query_runner.query.dateRange is not None
        assert query_runner.query.dateRange.date_from == "2020-01-09"
        assert query_runner.query.dateRange.date_to == "2020-01-20"
        assert query_runner.query.properties is None
        assert query_runner.query.breakdownFilter is None
        assert query_runner.query.trendsFilter is None

        query_runner.apply_dashboard_filters(DashboardFilter())

        assert query_runner.query.dateRange.date_from == "2020-01-09"
        assert query_runner.query.dateRange.date_to == "2020-01-20"
        assert query_runner.query.properties is None
        assert query_runner.query.breakdownFilter is None
        assert query_runner.query.trendsFilter is None

    def test_date_from_override_updates_whole_date_range(self):
        query_runner = self._create_query_runner(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            None,
        )

        assert query_runner.query.dateRange is not None
        assert query_runner.query.dateRange.date_from == "2020-01-09"
        assert query_runner.query.dateRange.date_to == "2020-01-20"
        assert query_runner.query.properties is None
        assert query_runner.query.breakdownFilter is None
        assert query_runner.query.trendsFilter is None

        query_runner.apply_dashboard_filters(DashboardFilter(date_from="-14d"))

        assert query_runner.query.dateRange.date_from == "-14d"
        assert query_runner.query.dateRange.date_to is None
        assert query_runner.query.properties is None  # type: ignore [unreachable]
        assert query_runner.query.breakdownFilter is None
        assert query_runner.query.trendsFilter is None

    def test_date_from_and_date_to_override_updates_whole_date_range(self):
        query_runner = self._create_query_runner(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            None,
        )

        assert query_runner.query.dateRange is not None
        assert query_runner.query.dateRange.date_from == "2020-01-09"
        assert query_runner.query.dateRange.date_to == "2020-01-20"
        assert query_runner.query.properties is None
        assert query_runner.query.breakdownFilter is None
        assert query_runner.query.trendsFilter is None

        query_runner.apply_dashboard_filters(DashboardFilter(date_from="2024-07-07", date_to="2024-07-14"))

        assert query_runner.query.dateRange.date_from == "2024-07-07"
        assert query_runner.query.dateRange.date_to == "2024-07-14"
        assert query_runner.query.properties is None
        assert query_runner.query.breakdownFilter is None
        assert query_runner.query.trendsFilter is None

    def test_properties_set_when_no_filters_present(self):
        query_runner = self._create_query_runner(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            None,
        )

        assert query_runner.query.dateRange is not None
        assert query_runner.query.dateRange.date_from == "2020-01-09"
        assert query_runner.query.dateRange.date_to == "2020-01-20"
        assert query_runner.query.properties is None
        assert query_runner.query.breakdownFilter is None
        assert query_runner.query.trendsFilter is None

        query_runner.apply_dashboard_filters(
            DashboardFilter(properties=[EventPropertyFilter(key="key", value="value", operator="exact")])
        )

        assert query_runner.query.dateRange.date_from == "2020-01-09"
        assert query_runner.query.dateRange.date_to == "2020-01-20"
        assert query_runner.query.properties == [EventPropertyFilter(key="key", value="value", operator="exact")]
        assert query_runner.query.breakdownFilter is None
        assert query_runner.query.trendsFilter is None

    def test_properties_list_extends_filters_list(self):
        query_runner = self._create_query_runner(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            None,
            properties=[EventPropertyFilter(key="abc", value="foo", operator="exact")],
        )

        assert query_runner.query.dateRange is not None
        assert query_runner.query.dateRange.date_from == "2020-01-09"
        assert query_runner.query.dateRange.date_to == "2020-01-20"
        assert query_runner.query.properties == [EventPropertyFilter(key="abc", value="foo", operator="exact")]
        assert query_runner.query.breakdownFilter is None
        assert query_runner.query.trendsFilter is None

        query_runner.apply_dashboard_filters(
            DashboardFilter(properties=[EventPropertyFilter(key="xyz", value="bar", operator="regex")])
        )

        assert query_runner.query.dateRange.date_from == "2020-01-09"
        assert query_runner.query.dateRange.date_to == "2020-01-20"
        assert query_runner.query.properties == PropertyGroupFilter(
            type=FilterLogicalOperator.AND_,
            values=[
                PropertyGroupFilterValue(
                    type=FilterLogicalOperator.AND_,
                    values=[
                        EventPropertyFilter(key="abc", value="foo", operator="exact"),
                    ],
                ),
                PropertyGroupFilterValue(
                    type=FilterLogicalOperator.AND_,
                    values=[
                        EventPropertyFilter(key="xyz", value="bar", operator="regex"),
                    ],
                ),
            ],
        )
        assert query_runner.query.breakdownFilter is None
        assert query_runner.query.trendsFilter is None

    def test_properties_list_extends_filters_group(self):
        query_runner = self._create_query_runner(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            None,
            properties=PropertyGroupFilter(
                type=FilterLogicalOperator.OR_,
                values=[
                    PropertyGroupFilterValue(
                        type=FilterLogicalOperator.OR_,
                        values=[EventPropertyFilter(key="abc", value="foo", operator="exact")],
                    ),
                    PropertyGroupFilterValue(
                        type=FilterLogicalOperator.AND_,
                        values=[EventPropertyFilter(key="klm", value="foo", operator="exact")],
                    ),
                ],
            ),
        )

        assert query_runner.query.dateRange is not None
        assert query_runner.query.dateRange.date_from == "2020-01-09"
        assert query_runner.query.dateRange.date_to == "2020-01-20"
        assert query_runner.query.properties == PropertyGroupFilter(
            type=FilterLogicalOperator.OR_,
            values=[
                PropertyGroupFilterValue(
                    type=FilterLogicalOperator.OR_,
                    values=[EventPropertyFilter(key="abc", value="foo", operator="exact")],
                ),
                PropertyGroupFilterValue(
                    type=FilterLogicalOperator.AND_,
                    values=[EventPropertyFilter(key="klm", value="foo", operator="exact")],
                ),
            ],
        )
        assert query_runner.query.breakdownFilter is None
        assert query_runner.query.trendsFilter is None

        query_runner.apply_dashboard_filters(
            DashboardFilter(
                properties=[
                    EventPropertyFilter(key="xyz", value="bar", operator="regex"),
                ]
            )
        )

        assert query_runner.query.dateRange.date_from == "2020-01-09"
        assert query_runner.query.dateRange.date_to == "2020-01-20"
        assert query_runner.query.properties == PropertyGroupFilter(
            type=FilterLogicalOperator.AND_,
            values=[
                PropertyGroupFilterValue(
                    type=FilterLogicalOperator.OR_,
                    values=[
                        PropertyGroupFilterValue(
                            type=FilterLogicalOperator.OR_,
                            values=[EventPropertyFilter(key="abc", value="foo", operator="exact")],
                        ),
                        PropertyGroupFilterValue(
                            type=FilterLogicalOperator.AND_,
                            values=[EventPropertyFilter(key="klm", value="foo", operator="exact")],
                        ),
                    ],
                ),
                PropertyGroupFilterValue(
                    type=FilterLogicalOperator.AND_,
                    values=[EventPropertyFilter(key="xyz", value="bar", operator="regex")],
                ),
            ],
        )
        assert query_runner.query.breakdownFilter is None
        assert query_runner.query.trendsFilter is None

    def test_breakdown_limit_is_not_removed_for_dashboard(self):
        query_runner = self._create_query_runner(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            None,
            breakdown=BreakdownFilter(breakdown="abc", breakdown_limit=5),
        )

        assert query_runner.query.dateRange is not None
        assert query_runner.query.dateRange.date_from == "2020-01-09"
        assert query_runner.query.dateRange.date_to == "2020-01-20"
        assert query_runner.query.properties is None
        assert query_runner.query.breakdownFilter == BreakdownFilter(breakdown="abc", breakdown_limit=5)
        assert query_runner.query.trendsFilter is None

        query_runner.apply_dashboard_filters(DashboardFilter())  #

        assert query_runner.query.dateRange.date_from == "2020-01-09"
        assert query_runner.query.dateRange.date_to == "2020-01-20"
        assert query_runner.query.properties is None
        assert query_runner.query.breakdownFilter == BreakdownFilter(breakdown="abc", breakdown_limit=5)  # Small enough
        assert query_runner.query.trendsFilter is None

        query_runner.query.breakdownFilter.breakdown_limit = 50

        query_runner.apply_dashboard_filters(DashboardFilter())

        assert query_runner.query.breakdownFilter == BreakdownFilter(breakdown="abc", breakdown_limit=50)

    def test_dashboard_breakdown_filter_updates_breakdown_filter(self):
        query_runner = self._create_query_runner(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            None,
            breakdown=BreakdownFilter(breakdown="abc", breakdown_limit=5),
        )

        assert query_runner.query.dateRange is not None
        assert query_runner.query.dateRange.date_from == "2020-01-09"
        assert query_runner.query.dateRange.date_to == "2020-01-20"
        assert query_runner.query.properties is None
        assert query_runner.query.breakdownFilter == BreakdownFilter(breakdown="abc", breakdown_limit=5)
        assert query_runner.query.trendsFilter is None

        query_runner.apply_dashboard_filters(
            DashboardFilter(
                breakdown_filter=BreakdownFilter(
                    breakdown="$feature/my-fabulous-feature", breakdown_type="event", breakdown_limit=10
                )
            )
        )

        assert query_runner.query.dateRange is not None
        assert query_runner.query.dateRange.date_from == "2020-01-09"
        assert query_runner.query.dateRange.date_to == "2020-01-20"
        assert query_runner.query.properties is None
        assert query_runner.query.breakdownFilter == BreakdownFilter(
            breakdown="$feature/my-fabulous-feature", breakdown_type="event", breakdown_limit=10
        )
        assert query_runner.query.trendsFilter is None

    def test_compare_is_removed_for_all_time_range(self):
        query_runner = self._create_query_runner(
            "2024-07-07",
            "2024-07-14",
            IntervalType.DAY,
            None,
            trends_filters=TrendsFilter(),
            compare_filters=CompareFilter(compare=True),
        )

        assert query_runner.query.dateRange is not None
        assert query_runner.query.dateRange.date_from == "2024-07-07"
        assert query_runner.query.dateRange.date_to == "2024-07-14"
        assert query_runner.query.properties is None
        assert query_runner.query.breakdownFilter is None
        assert query_runner.query.trendsFilter == TrendsFilter()
        assert query_runner.query.compareFilter == CompareFilter(compare=True)

        query_runner.apply_dashboard_filters(DashboardFilter(date_from="all"))

        assert query_runner.query.dateRange.date_from == "all"
        assert query_runner.query.dateRange.date_to is None
        assert query_runner.query.properties is None  # type: ignore [unreachable]
        assert query_runner.query.breakdownFilter is None
        assert query_runner.query.trendsFilter == TrendsFilter()
        assert query_runner.query.compareFilter == CompareFilter(
            compare=False
        )  # There's no previous period for the "all time" date range
