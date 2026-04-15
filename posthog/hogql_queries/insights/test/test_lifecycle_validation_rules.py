from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import EventsNode, LifecycleDataWarehouseNode, LifecycleQuery

from posthog.hogql_queries.insights.lifecycle_validation import (
    RequireLifecycleDataWarehouseSeriesForCustomAggregationTarget,
)
from posthog.hogql_queries.legacy_compatibility.clean_properties import clean_entity_properties
from posthog.hogql_queries.validation.rules import DisallowUnsupportedDataWarehouseSettings
from posthog.hogql_queries.validation.validation import QueryValidationContext


class TestLifecycleValidationRules(BaseTest):
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

    def test_custom_aggregation_target_requires_data_warehouse_series(self):
        query = LifecycleQuery(
            customAggregationTarget=True,
            series=[EventsNode(event="$pageview")],
        )

        with self.assertRaises(ValidationError) as context:
            RequireLifecycleDataWarehouseSeriesForCustomAggregationTarget().validate(self._context(query))

        self.assertIn(
            "Custom entity aggregation target is not supported for lifecycle insights without a data warehouse series.",
            str(context.exception),
        )

    def test_custom_aggregation_target_allows_data_warehouse_series(self):
        query = LifecycleQuery(
            customAggregationTarget=True,
            series=self._data_warehouse_series(),
        )

        RequireLifecycleDataWarehouseSeriesForCustomAggregationTarget().validate(self._context(query))

    @parameterized.expand(
        [
            (
                "filters",
                {"properties": clean_entity_properties([{"key": "text", "value": "new", "type": "data_warehouse"}])},
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

    def test_allows_supported_settings_without_data_warehouse_series(self):
        query = LifecycleQuery(
            filterTestAccounts=True,
            samplingFactor=0.1,
            series=[EventsNode(event="$pageview")],
        )

        DisallowUnsupportedDataWarehouseSettings().validate(self._context(query))
