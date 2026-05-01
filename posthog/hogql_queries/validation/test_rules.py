from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    EventsNode,
    FilterLogicalOperator,
    LifecycleDataWarehouseNode,
    LifecycleQuery,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
)

from posthog.hogql_queries.validation.rules import DisallowUnsupportedDataWarehouseSettings, RequireAtLeastOneSeries
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
