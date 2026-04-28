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

    def test_disallows_multi_breakdowns_for_data_warehouse_series(self) -> None:
        query = TrendsQuery(
            series=self._data_warehouse_series(),
            breakdownFilter=BreakdownFilter(
                breakdowns=[
                    Breakdown(property="$browser", type=BreakdownType.EVENT),
                    Breakdown(property="$geoip_country_code", type=BreakdownType.PERSON),
                ]
            ),
        )

        with self.assertRaises(ValidationError) as context:
            ValidateDataWarehouseBreakdown().validate(self._context(query))

        self.assertIn(
            "Multi-breakdowns not supported for trends insights with a data warehouse series.",
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
