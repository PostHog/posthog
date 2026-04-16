from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from rest_framework.exceptions import ValidationError

from posthog.schema import EventsNode, LifecycleDataWarehouseNode, LifecycleQuery

from posthog.hogql_queries.insights.lifecycle.lifecycle_validation_rules import (
    RequireLifecycleDataWarehouseSeriesForCustomAggregationTarget,
)
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
        self.assertEqual(
            context.exception.get_codes(),
            ["lifecycle_custom_aggregation_target_requires_data_warehouse_series"],
        )

    def test_custom_aggregation_target_allows_data_warehouse_series(self):
        query = LifecycleQuery(
            customAggregationTarget=True,
            series=self._data_warehouse_series(),
        )

        RequireLifecycleDataWarehouseSeriesForCustomAggregationTarget().validate(self._context(query))
