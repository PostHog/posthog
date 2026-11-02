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
    DataWarehouseNode,
    DataWarehousePropertyFilter,
    EntityType,
    EventPropertyFilter,
    EventsNode,
    FilterLogicalOperator,
    LifecycleDataWarehouseNode,
    LifecycleQuery,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    PropertyOperator,
    RetentionEntity,
    RetentionFilter,
    RetentionQuery,
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


FLAG_CALLS_TABLE = "posthog.flag_evaluations"
MESSAGES_SERIES = LifecycleDataWarehouseNode(
    id="messages",
    table_name="messages",
    timestamp_field="sent_at",
    aggregation_target_field="person_id",
    created_at_field="signed_up_at",
)
FLAG_CALLS_SERIES = LifecycleDataWarehouseNode(
    id=FLAG_CALLS_TABLE,
    table_name=FLAG_CALLS_TABLE,
    timestamp_field="timestamp",
    aggregation_target_field="person_id",
    created_at_field="timestamp",
)
EVENT_FILTER = EventPropertyFilter(key="$browser", value="Chrome", operator=PropertyOperator.EXACT)


def _trends_warehouse_series(table_name: str) -> DataWarehouseNode:
    return DataWarehouseNode(
        id=table_name,
        table_name=table_name,
        timestamp_field="timestamp",
        distinct_id_field="distinct_id",
        id_field="uuid",
    )


def _retention_warehouse_entity(table_name: str) -> RetentionEntity:
    return RetentionEntity(
        id=table_name,
        type=EntityType.DATA_WAREHOUSE,
        table_name=table_name,
        timestamp_field="timestamp",
        aggregation_target_field="person_id",
    )


class TestDisallowUnsupportedDataWarehouseSettings(BaseTest):
    def _context(self, query: TrendsQuery | LifecycleQuery | RetentionQuery) -> QueryValidationContext:
        runner = MagicMock(query=query, team=self.team, user=None)
        return QueryValidationContext(query=query, team=self.team, user=None, runner=runner)

    @parameterized.expand(
        [
            (
                "filters",
                LifecycleQuery(
                    series=[MESSAGES_SERIES],
                    properties=[DataWarehousePropertyFilter(key="text", value="new", operator=PropertyOperator.EXACT)],
                ),
                "Filters are not supported for lifecycle insights with a data warehouse series.",
            ),
            (
                "test_account_filters",
                LifecycleQuery(series=[MESSAGES_SERIES], filterTestAccounts=True),
                "Test account filters are not supported for lifecycle insights with a data warehouse series.",
            ),
            (
                "sampling",
                LifecycleQuery(series=[MESSAGES_SERIES], samplingFactor=0.1),
                "Sampling is not supported for lifecycle insights with a data warehouse series.",
            ),
            (
                "multiple_settings",
                LifecycleQuery(series=[MESSAGES_SERIES], filterTestAccounts=True, samplingFactor=0.1),
                "Test account filters and sampling are not supported for lifecycle insights with a data warehouse series.",
            ),
            (
                "flag_calls_beside_another_warehouse_table",
                TrendsQuery(
                    series=[_trends_warehouse_series(FLAG_CALLS_TABLE), _trends_warehouse_series("messages")],
                    filterTestAccounts=True,
                ),
                "Test account filters are not supported for trends insights with a data warehouse series.",
            ),
            (
                "flag_calls_target_returning_on_another_warehouse_table",
                RetentionQuery(
                    filterTestAccounts=True,
                    retentionFilter=RetentionFilter(
                        targetEntity=_retention_warehouse_entity(FLAG_CALLS_TABLE),
                        returningEntity=_retention_warehouse_entity("messages"),
                    ),
                ),
                "Test account filters are not supported for retention insights with a data warehouse series.",
            ),
            (
                "flag_calls_sampling",
                LifecycleQuery(series=[FLAG_CALLS_SERIES], samplingFactor=0.1),
                "Sampling is not supported for lifecycle insights with a data warehouse series.",
            ),
        ]
    )
    def test_disallows_unsupported_data_warehouse_settings(
        self, _name: str, query: TrendsQuery | LifecycleQuery | RetentionQuery, expected_error: str
    ):
        with self.assertRaises(ValidationError) as context:
            DisallowUnsupportedDataWarehouseSettings().validate(self._context(query))

        self.assertIn(expected_error, str(context.exception))
        self.assertEqual(context.exception.get_codes(), ["data_warehouse_series_unsupported_settings"])

    @parameterized.expand(
        [
            (
                "events_only",
                LifecycleQuery(filterTestAccounts=True, samplingFactor=0.1, series=[EventsNode(event="$pageview")]),
            ),
            (
                "flag_calls_only",
                LifecycleQuery(filterTestAccounts=True, properties=[EVENT_FILTER], series=[FLAG_CALLS_SERIES]),
            ),
            (
                "flag_calls_beside_events",
                TrendsQuery(
                    filterTestAccounts=True,
                    properties=[EVENT_FILTER],
                    series=[EventsNode(event="$pageview"), _trends_warehouse_series(FLAG_CALLS_TABLE)],
                ),
            ),
            (
                "retention_flag_calls_target_returning_on_events",
                RetentionQuery(
                    filterTestAccounts=True,
                    properties=[EVENT_FILTER],
                    retentionFilter=RetentionFilter(
                        targetEntity=_retention_warehouse_entity(FLAG_CALLS_TABLE),
                        returningEntity=RetentionEntity(id="$pageview", type=EntityType.EVENTS),
                    ),
                ),
            ),
        ]
    )
    def test_allows_supported_settings(self, _name: str, query: TrendsQuery | LifecycleQuery | RetentionQuery):
        DisallowUnsupportedDataWarehouseSettings().validate(self._context(query))

    def test_allows_empty_property_groups_for_data_warehouse_series(self):
        query = LifecycleQuery(
            series=[MESSAGES_SERIES],
            properties=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[PropertyGroupFilterValue(type=FilterLogicalOperator.AND_, values=[])],
            ),
        )

        DisallowUnsupportedDataWarehouseSettings().validate(self._context(query))

    def test_allows_empty_property_list_for_data_warehouse_series(self):
        query = LifecycleQuery(
            series=[MESSAGES_SERIES],
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
