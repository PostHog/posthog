from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from django.test import SimpleTestCase

import pydantic
from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    BreakdownFilter,
    BreakdownType,
    CompareFilter,
    EventsNode,
    FilterLogicalOperator,
    LifecycleDataWarehouseNode,
    LifecycleQuery,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    StickinessQuery,
    TrendsQuery,
)

from posthog.hogql.constants import MAX_EXPANDED_INSIGHT_QUERIES

from posthog.hogql_queries.validation.rules import (
    DisallowUnsupportedDataWarehouseSettings,
    RequireAtLeastOneSeries,
    expanded_series_count,
    validate_series_fan_out,
)
from posthog.hogql_queries.validation.validation import QueryValidationContext


class TestRequireAtLeastOneSeries(BaseTest):
    def _context(self, query: LifecycleQuery) -> QueryValidationContext:
        runner = MagicMock(query=query, team=self.team, user=None)
        return QueryValidationContext(query=query, team=self.team, user=None, runner=runner)

    def test_raises_for_empty_series(self):
        query = LifecycleQuery(series=[])

        with self.assertRaises(ValidationError) as context:
            RequireAtLeastOneSeries().validate(self._context(query))

        self.assertIn("Lifecycle insights require at least one series.", str(context.exception))
        self.assertEqual(context.exception.get_codes(), ["insight_requires_at_least_one_series"])

    def test_allows_non_empty_series(self):
        query = LifecycleQuery(series=[EventsNode(event="$pageview")])

        RequireAtLeastOneSeries().validate(self._context(query))


class TestDisallowUnsupportedDataWarehouseSettings(BaseTest):
    def _context(self, query: LifecycleQuery) -> QueryValidationContext:
        runner = MagicMock(query=query, team=self.team, user=None)
        return QueryValidationContext(query=query, team=self.team, user=None, runner=runner)

    def _data_warehouse_series(self) -> list[LifecycleDataWarehouseNode]:
        return [
            LifecycleDataWarehouseNode(
                id="messages",
                table_name="messages",
                timestamp_field="sent_at",
                aggregation_target_field="person_id",
                created_at_field="signed_up_at",
            )
        ]

    @parameterized.expand(
        [
            (
                "filters",
                {"properties": [{"key": "text", "value": "new", "operator": "exact", "type": "data_warehouse"}]},
                "Filters are not supported for lifecycle insights with a data warehouse series.",
            ),
            (
                "test_account_filters",
                {"filterTestAccounts": True},
                "Test account filters are not supported for lifecycle insights with a data warehouse series.",
            ),
            (
                "sampling",
                {"samplingFactor": 0.1},
                "Sampling is not supported for lifecycle insights with a data warehouse series.",
            ),
            (
                "multiple_settings",
                {"filterTestAccounts": True, "samplingFactor": 0.1},
                "Test account filters and sampling are not supported for lifecycle insights with a data warehouse series.",
            ),
        ]
    )
    def test_disallows_unsupported_data_warehouse_settings(self, _name, query_kwargs, expected_error):
        query = LifecycleQuery(series=self._data_warehouse_series(), **query_kwargs)

        with self.assertRaises(ValidationError) as context:
            DisallowUnsupportedDataWarehouseSettings().validate(self._context(query))

        self.assertIn(expected_error, str(context.exception))
        self.assertEqual(context.exception.get_codes(), ["data_warehouse_series_unsupported_settings"])

    def test_allows_supported_settings_without_data_warehouse_series(self):
        query = LifecycleQuery(
            filterTestAccounts=True,
            samplingFactor=0.1,
            series=[EventsNode(event="$pageview")],
        )

        DisallowUnsupportedDataWarehouseSettings().validate(self._context(query))

    def test_allows_empty_property_groups_for_data_warehouse_series(self):
        query = LifecycleQuery(
            series=self._data_warehouse_series(),
            properties=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[PropertyGroupFilterValue(type=FilterLogicalOperator.AND_, values=[])],
            ),
        )

        DisallowUnsupportedDataWarehouseSettings().validate(self._context(query))

    def test_allows_empty_property_list_for_data_warehouse_series(self):
        query = LifecycleQuery(
            series=self._data_warehouse_series(),
            properties=[],
        )

        DisallowUnsupportedDataWarehouseSettings().validate(self._context(query))


def _series(count: int) -> list[EventsNode]:
    return [EventsNode(event=f"event_{index}") for index in range(count)]


def _cohort_breakdown(count: int) -> BreakdownFilter:
    return BreakdownFilter(breakdown_type=BreakdownType.COHORT, breakdown=list(range(1, count + 1)))


class TestValidateSeriesFanOut(SimpleTestCase):
    @parameterized.expand(
        [
            ("at_the_limit", 200, None, False),
            ("compare_doubles_up_to_the_limit", 100, None, True),
            ("cohorts_multiply_up_to_the_limit", 40, _cohort_breakdown(5), False),
            ("every_factor_together_at_the_limit", 25, _cohort_breakdown(4), True),
        ]
    )
    def test_allows_expansions_within_the_limit(
        self, _name: str, series_count: int, breakdown_filter: BreakdownFilter | None, compare: bool
    ) -> None:
        query = TrendsQuery(
            series=_series(series_count),
            breakdownFilter=breakdown_filter,
            compareFilter=CompareFilter(compare=compare),
        )

        validate_series_fan_out(query, cohort_breakdown_expands=True)

    @parameterized.expand(
        [
            ("compare_doubles_past_the_limit", 101, None, True, 202),
            ("cohorts_multiply_past_the_limit", 50, _cohort_breakdown(5), False, 250),
            ("every_factor_together_past_the_limit", 34, _cohort_breakdown(3), True, 204),
        ]
    )
    def test_rejects_expansions_over_the_limit(
        self, _name: str, series_count: int, breakdown_filter: BreakdownFilter | None, compare: bool, expected: int
    ) -> None:
        query = TrendsQuery(
            series=_series(series_count),
            breakdownFilter=breakdown_filter,
            compareFilter=CompareFilter(compare=compare),
        )

        with self.assertRaises(ValidationError) as context:
            validate_series_fan_out(query, cohort_breakdown_expands=True)

        self.assertIn(f"needs {expected} queries", str(context.exception))
        self.assertEqual(context.exception.get_codes(), ["insight_series_fan_out_too_large"])

    def test_breakdown_that_does_not_expand_leaves_the_series_count_alone(self) -> None:
        query = TrendsQuery(
            series=_series(200),
            breakdownFilter=BreakdownFilter(
                breakdown_type=BreakdownType.EVENT, breakdown=[f"prop_{index}" for index in range(10)]
            ),
        )

        validate_series_fan_out(query, cohort_breakdown_expands=False)

    def test_rejects_stickiness_expansion_over_the_limit(self) -> None:
        query = StickinessQuery(series=_series(101), compareFilter=CompareFilter(compare=True))

        with self.assertRaises(ValidationError) as context:
            validate_series_fan_out(query, cohort_breakdown_expands=False)

        self.assertEqual(context.exception.get_codes(), ["insight_series_fan_out_too_large"])

    def test_conjoined_cohort_breakdown_does_not_multiply_the_series(self) -> None:
        query = TrendsQuery(series=_series(150), breakdownFilter=_cohort_breakdown(5))

        self.assertEqual(expanded_series_count(query, cohort_breakdown_expands=False), 150)
        self.assertEqual(expanded_series_count(query, cohort_breakdown_expands=True), 750)

        validate_series_fan_out(query, cohort_breakdown_expands=False)


class TestSeriesLengthSchemaLimit(SimpleTestCase):
    @parameterized.expand([("trends", TrendsQuery), ("stickiness", StickinessQuery)])
    def test_series_longer_than_the_limit_is_rejected_before_the_runner(self, _name: str, query_class) -> None:
        query_class(series=_series(MAX_EXPANDED_INSIGHT_QUERIES))

        with self.assertRaises(pydantic.ValidationError):
            query_class(series=_series(MAX_EXPANDED_INSIGHT_QUERIES + 1))
