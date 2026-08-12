from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    Breakdown,
    BreakdownFilter,
    BreakdownType,
    DataWarehouseNode,
    DateRange,
    EventsNode,
    MultipleBreakdownType,
    PropertyMathType,
    TrendsFilter,
    TrendsQuery,
)

from posthog.hogql_queries.insights.trends.trend_validation_rules import (
    DisallowDaysOfWeekWithSmoothing,
    DisallowUnsupportedPropertyMathForHistogramBreakdown,
    ValidateDataWarehouseBreakdown,
)
from posthog.hogql_queries.validation.validation import QueryValidationContext


class TestValidateDataWarehouseBreakdown(BaseTest):
    def _context(self, query: TrendsQuery) -> QueryValidationContext[TrendsQuery]:
        runner = MagicMock(query=query, team=self.team, user=None)
        return QueryValidationContext(query=query, team=self.team, user=None, runner=runner)

    def _data_warehouse_series(self) -> list[DataWarehouseNode]:
        return [
            DataWarehouseNode(
                id="messages",
                table_name="messages",
                timestamp_field="sent_at",
                id_field="message_id",
                distinct_id_field="person_id",
            )
        ]

    def test_allows_queries_without_data_warehouse_series(self) -> None:
        query = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            breakdownFilter=BreakdownFilter(breakdown="$browser"),
        )

        ValidateDataWarehouseBreakdown().validate(self._context(query))

    def test_allows_data_warehouse_series_without_breakdown(self) -> None:
        query = TrendsQuery(series=self._data_warehouse_series())

        ValidateDataWarehouseBreakdown().validate(self._context(query))

    @parameterized.expand(
        [
            (
                "data_warehouse_type",
                BreakdownFilter(breakdown="plan", breakdown_type=BreakdownType.DATA_WAREHOUSE),
            ),
            (
                "hogql_type",
                BreakdownFilter(breakdown="status", breakdown_type=BreakdownType.HOGQL),
            ),
        ]
    )
    def test_allows_supported_single_breakdowns(self, _name: str, breakdown_filter: BreakdownFilter) -> None:
        query = TrendsQuery(
            series=self._data_warehouse_series(),
            breakdownFilter=breakdown_filter,
        )

        ValidateDataWarehouseBreakdown().validate(self._context(query))

    @parameterized.expand(
        [
            (
                "default_event_breakdown",
                BreakdownFilter(breakdown="$browser"),
            ),
            (
                "explicit_event_breakdown",
                BreakdownFilter(breakdown="$browser", breakdown_type=BreakdownType.EVENT),
            ),
            (
                "person_breakdown",
                BreakdownFilter(breakdown="$geoip_country_code", breakdown_type=BreakdownType.PERSON),
            ),
        ]
    )
    def test_disallows_unsupported_single_breakdowns(self, _name: str, breakdown_filter: BreakdownFilter) -> None:
        query = TrendsQuery(
            series=self._data_warehouse_series(),
            breakdownFilter=breakdown_filter,
        )

        with self.assertRaises(ValidationError) as context:
            ValidateDataWarehouseBreakdown().validate(self._context(query))

        self.assertIn(
            "Event based breakdowns are not supported for trends insights with a data warehouse series.",
            str(context.exception),
        )
        self.assertEqual(
            context.exception.get_codes(),
            ["data_warehouse_series_unsupported_breakdown"],
        )

    @parameterized.expand(
        [
            (
                "two_hogql_breakdowns",
                [
                    Breakdown(property="status", type=MultipleBreakdownType.HOGQL),
                    Breakdown(property="plan", type=MultipleBreakdownType.HOGQL),
                ],
            ),
            (
                "hogql_and_data_warehouse",
                [
                    Breakdown(property="status", type=MultipleBreakdownType.HOGQL),
                    Breakdown(property="plan", type=MultipleBreakdownType.DATA_WAREHOUSE),
                ],
            ),
            (
                "two_data_warehouse_breakdowns",
                [
                    Breakdown(property="plan", type=MultipleBreakdownType.DATA_WAREHOUSE),
                    Breakdown(property="region", type=MultipleBreakdownType.DATA_WAREHOUSE),
                ],
            ),
            (
                "three_supported_breakdowns",
                [
                    Breakdown(property="status", type=MultipleBreakdownType.HOGQL),
                    Breakdown(property="plan", type=MultipleBreakdownType.DATA_WAREHOUSE),
                    Breakdown(property="region", type=MultipleBreakdownType.HOGQL),
                ],
            ),
        ]
    )
    def test_allows_multi_breakdowns_with_supported_types(self, _name: str, breakdowns: list[Breakdown]) -> None:
        query = TrendsQuery(
            series=self._data_warehouse_series(),
            breakdownFilter=BreakdownFilter(breakdowns=breakdowns),
        )

        ValidateDataWarehouseBreakdown().validate(self._context(query))

    @parameterized.expand(
        [
            (
                "event_and_person",
                [
                    Breakdown(property="$browser", type=MultipleBreakdownType.EVENT),
                    Breakdown(property="$geoip_country_code", type=MultipleBreakdownType.PERSON),
                ],
            ),
            (
                "hogql_and_event",
                [
                    Breakdown(property="status", type=MultipleBreakdownType.HOGQL),
                    Breakdown(property="$browser", type=MultipleBreakdownType.EVENT),
                ],
            ),
            (
                "data_warehouse_and_person",
                [
                    Breakdown(property="plan", type=MultipleBreakdownType.DATA_WAREHOUSE),
                    Breakdown(property="$geoip_country_code", type=MultipleBreakdownType.PERSON),
                ],
            ),
            (
                "hogql_and_data_warehouse_person_property",
                [
                    Breakdown(property="status", type=MultipleBreakdownType.HOGQL),
                    Breakdown(property="plan", type=MultipleBreakdownType.DATA_WAREHOUSE_PERSON_PROPERTY),
                ],
            ),
        ]
    )
    def test_disallows_multi_breakdowns_with_any_unsupported_type(
        self, _name: str, breakdowns: list[Breakdown]
    ) -> None:
        query = TrendsQuery(
            series=self._data_warehouse_series(),
            breakdownFilter=BreakdownFilter(breakdowns=breakdowns),
        )

        with self.assertRaises(ValidationError) as context:
            ValidateDataWarehouseBreakdown().validate(self._context(query))

        self.assertIn(
            "Event based breakdowns are not supported for trends insights with a data warehouse series.",
            str(context.exception),
        )
        self.assertEqual(
            context.exception.get_codes(),
            ["data_warehouse_series_unsupported_breakdown"],
        )

    @parameterized.expand(
        [
            (
                "data_warehouse_type",
                Breakdown(property="plan", type=MultipleBreakdownType.DATA_WAREHOUSE),
            ),
            (
                "hogql_type",
                Breakdown(property="status", type=MultipleBreakdownType.HOGQL),
            ),
        ]
    )
    def test_allows_supported_single_item_multi_breakdown(self, _name: str, breakdown: Breakdown) -> None:
        query = TrendsQuery(
            series=self._data_warehouse_series(),
            breakdownFilter=BreakdownFilter(breakdowns=[breakdown]),
        )

        ValidateDataWarehouseBreakdown().validate(self._context(query))

    @parameterized.expand(
        [
            (
                "default_event_type",
                Breakdown(property="$browser"),
            ),
            (
                "explicit_event_type",
                Breakdown(property="$browser", type=MultipleBreakdownType.EVENT),
            ),
            (
                "person_type",
                Breakdown(property="$geoip_country_code", type=MultipleBreakdownType.PERSON),
            ),
            (
                "data_warehouse_person_property_type",
                Breakdown(property="plan", type=MultipleBreakdownType.DATA_WAREHOUSE_PERSON_PROPERTY),
            ),
        ]
    )
    def test_disallows_unsupported_single_item_multi_breakdown(self, _name: str, breakdown: Breakdown) -> None:
        query = TrendsQuery(
            series=self._data_warehouse_series(),
            breakdownFilter=BreakdownFilter(breakdowns=[breakdown]),
        )

        with self.assertRaises(ValidationError) as context:
            ValidateDataWarehouseBreakdown().validate(self._context(query))

        self.assertIn(
            "Event based breakdowns are not supported for trends insights with a data warehouse series.",
            str(context.exception),
        )
        self.assertEqual(
            context.exception.get_codes(),
            ["data_warehouse_series_unsupported_breakdown"],
        )


class TestDisallowUnsupportedPropertyMathForHistogramBreakdown(BaseTest):
    def _context(self, query: TrendsQuery) -> QueryValidationContext[TrendsQuery]:
        runner = MagicMock(query=query, team=self.team, user=None)
        return QueryValidationContext(query=query, team=self.team, user=None, runner=runner)

    @parameterized.expand(
        [
            ("no_breakdown", PropertyMathType.MEDIAN, None),
            ("breakdown_without_bins", PropertyMathType.MEDIAN, BreakdownFilter(breakdown="prop")),
            (
                "supported_math_with_bins",
                PropertyMathType.AVG,
                BreakdownFilter(breakdown="prop", breakdown_histogram_bin_count=10),
            ),
            (
                "multi_breakdown_without_bins",
                PropertyMathType.P90,
                BreakdownFilter(breakdowns=[Breakdown(property="prop")]),
            ),
        ]
    )
    def test_allows_supported_combinations(
        self, _name: str, math: PropertyMathType, breakdown_filter: BreakdownFilter | None
    ) -> None:
        query = TrendsQuery(
            series=[EventsNode(event="$pageview", math=math, math_property="prop")],
            breakdownFilter=breakdown_filter,
        )

        DisallowUnsupportedPropertyMathForHistogramBreakdown().validate(self._context(query))

    @parameterized.expand(
        [
            (
                "single_breakdown",
                PropertyMathType.MEDIAN,
                BreakdownFilter(breakdown="prop", breakdown_histogram_bin_count=10),
            ),
            (
                "multi_breakdown",
                PropertyMathType.P90,
                BreakdownFilter(breakdowns=[Breakdown(property="prop", histogram_bin_count=10)]),
            ),
        ]
    )
    def test_disallows_unsupported_math_with_histogram_breakdown(
        self, _name: str, math: PropertyMathType, breakdown_filter: BreakdownFilter
    ) -> None:
        query = TrendsQuery(
            series=[EventsNode(event="$pageview", math=math, math_property="prop")],
            breakdownFilter=breakdown_filter,
        )

        with self.assertRaises(ValidationError) as context:
            DisallowUnsupportedPropertyMathForHistogramBreakdown().validate(self._context(query))

        self.assertEqual(
            context.exception.get_codes(),
            ["property_math_unsupported_with_histogram_breakdown"],
        )

    def test_error_message_names_the_unsupported_math_types(self) -> None:
        query = TrendsQuery(
            series=[
                EventsNode(event="$pageview", math=PropertyMathType.MEDIAN, math_property="prop"),
                EventsNode(event="$pageview", math=PropertyMathType.SUM, math_property="prop"),
            ],
            breakdownFilter=BreakdownFilter(breakdown="prop", breakdown_histogram_bin_count=10),
        )

        with self.assertRaises(ValidationError) as context:
            DisallowUnsupportedPropertyMathForHistogramBreakdown().validate(self._context(query))

        self.assertIn("Median is not supported", str(context.exception))


class TestDisallowDaysOfWeekWithSmoothing(BaseTest):
    def _context(self, query: TrendsQuery) -> QueryValidationContext[TrendsQuery]:
        runner = MagicMock(query=query, team=self.team, user=None)
        return QueryValidationContext(query=query, team=self.team, user=None, runner=runner)

    @parameterized.expand(
        [
            ("smoothing_without_days_restriction", TrendsFilter(smoothingIntervals=7), None),
            ("days_restriction_without_smoothing", None, [1, 2]),
            ("smoothing_with_full_week", TrendsFilter(smoothingIntervals=7), [1, 2, 3, 4, 5, 6, 7]),
            ("smoothing_interval_of_one", TrendsFilter(smoothingIntervals=1), [1, 2]),
        ]
    )
    def test_allows(self, _name: str, trends_filter: TrendsFilter | None, days_of_week: list[int] | None) -> None:
        query = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            trendsFilter=trends_filter,
            dateRange=DateRange(daysOfWeek=days_of_week),
        )

        DisallowDaysOfWeekWithSmoothing().validate(self._context(query))

    def test_disallows_smoothing_with_days_restriction(self) -> None:
        query = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            trendsFilter=TrendsFilter(smoothingIntervals=7),
            dateRange=DateRange(daysOfWeek=[1, 2, 3, 4, 5]),
        )

        with self.assertRaises(ValidationError) as context:
            DisallowDaysOfWeekWithSmoothing().validate(self._context(query))

        self.assertEqual(context.exception.get_codes(), ["days_of_week_unsupported_with_smoothing"])
