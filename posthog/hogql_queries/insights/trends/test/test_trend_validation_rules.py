from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    Breakdown,
    BreakdownFilter,
    BreakdownType,
    DataWarehouseNode,
    EventsNode,
    MultipleBreakdownType,
    TrendsQuery,
)

from posthog.hogql_queries.insights.trends.trend_validation_rules import ValidateDataWarehouseBreakdown
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
                "single_data_warehouse_type",
                [Breakdown(property="plan", type=MultipleBreakdownType.DATA_WAREHOUSE)],
            ),
            (
                "single_hogql_type",
                [Breakdown(property="status", type=MultipleBreakdownType.HOGQL)],
            ),
            (
                "multiple_data_warehouse_types",
                [
                    Breakdown(property="plan", type=MultipleBreakdownType.DATA_WAREHOUSE),
                    Breakdown(property="status", type=MultipleBreakdownType.DATA_WAREHOUSE),
                ],
            ),
            (
                "multiple_hogql_types",
                [
                    Breakdown(property="properties.plan", type=MultipleBreakdownType.HOGQL),
                    Breakdown(property="properties.status", type=MultipleBreakdownType.HOGQL),
                ],
            ),
            (
                "multiple_mixed_supported_types",
                [
                    Breakdown(property="plan", type=MultipleBreakdownType.DATA_WAREHOUSE),
                    Breakdown(property="properties.status", type=MultipleBreakdownType.HOGQL),
                ],
            ),
        ]
    )
    def test_allows_supported_multi_breakdowns(self, _name: str, breakdowns: list[Breakdown]) -> None:
        query = TrendsQuery(
            series=self._data_warehouse_series(),
            breakdownFilter=BreakdownFilter(breakdowns=breakdowns),
        )

        ValidateDataWarehouseBreakdown().validate(self._context(query))

    @parameterized.expand(
        [
            (
                "single_default_event_type",
                [Breakdown(property="$browser")],
            ),
            (
                "single_explicit_event_type",
                [Breakdown(property="$browser", type=MultipleBreakdownType.EVENT)],
            ),
            (
                "single_person_type",
                [Breakdown(property="$geoip_country_code", type=MultipleBreakdownType.PERSON)],
            ),
            (
                "single_data_warehouse_person_property_type",
                [Breakdown(property="plan", type=MultipleBreakdownType.DATA_WAREHOUSE_PERSON_PROPERTY)],
            ),
            (
                "multiple_with_unsupported_second_item",
                [
                    Breakdown(property="plan", type=MultipleBreakdownType.DATA_WAREHOUSE),
                    Breakdown(property="$browser", type=MultipleBreakdownType.EVENT),
                ],
            ),
            (
                "multiple_with_unsupported_first_item",
                [
                    Breakdown(property="$browser", type=MultipleBreakdownType.EVENT),
                    Breakdown(property="plan", type=MultipleBreakdownType.DATA_WAREHOUSE),
                ],
            ),
        ]
    )
    def test_disallows_unsupported_multi_breakdown_items(self, _name: str, breakdowns: list[Breakdown]) -> None:
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
