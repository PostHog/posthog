from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import AggregationType, EntityType, RetentionFilter, RetentionQuery, TimeWindowMode

from posthog.hogql_queries.insights.retention.retention_validation_rules import DisallowCumulativeWith24HourWindows
from posthog.hogql_queries.validation.rules import DisallowUnsupportedDataWarehouseSettings
from posthog.hogql_queries.validation.validation import QueryValidationContext


class TestRetentionValidationRules(BaseTest):
    def _context(self, query: RetentionQuery) -> QueryValidationContext:
        runner = MagicMock(query=query, team=self.team, user=None)
        return QueryValidationContext(query=query, team=self.team, user=None, runner=runner)

    def _data_warehouse_entity(self) -> dict[str, str]:
        return {
            "id": "signups",
            "table_name": "signups",
            "timestamp_field": "signed_up_at",
            "aggregation_target_field": "person_id",
            "type": EntityType.DATA_WAREHOUSE,
        }

    @parameterized.expand(
        [
            ("non_cumulative_default_window", False, None, False),
            ("cumulative_default_window", True, None, False),
            ("non_cumulative_24_hour_windows", False, TimeWindowMode.FIELD_24_HOUR_WINDOWS, False),
            ("cumulative_24_hour_windows", True, TimeWindowMode.FIELD_24_HOUR_WINDOWS, True),
        ]
    )
    def test_disallow_cumulative_with_24h_windows(
        self, _name: str, cumulative: bool, time_window_mode: TimeWindowMode | None, raises_error: bool
    ) -> None:
        query = RetentionQuery(retentionFilter=RetentionFilter(cumulative=cumulative, timeWindowMode=time_window_mode))

        if not raises_error:
            DisallowCumulativeWith24HourWindows().validate(self._context(query))
            return

        with self.assertRaises(ValidationError) as context:
            DisallowCumulativeWith24HourWindows().validate(self._context(query))

        self.assertIn("Cumulative retention is not supported for 24 hour windows.", str(context.exception))

    @parameterized.expand(
        [
            (
                "filters",
                {"properties": [{"key": "text", "value": "new", "operator": "exact", "type": "data_warehouse"}]},
                "Filters are not supported for retention insights with a data warehouse series.",
            ),
            (
                "test_account_filters",
                {"filterTestAccounts": True},
                "Test account filters are not supported for retention insights with a data warehouse series.",
            ),
            (
                "sampling",
                {"samplingFactor": 0.1},
                "Sampling is not supported for retention insights with a data warehouse series.",
            ),
            (
                "multiple_settings",
                {"filterTestAccounts": True, "samplingFactor": 0.1},
                "Test account filters and sampling are not supported for retention insights with a data warehouse series.",
            ),
        ]
    )
    def test_disallows_unsupported_data_warehouse_settings(self, _name, query_kwargs, expected_error):
        query = RetentionQuery(
            retentionFilter=RetentionFilter(targetEntity=self._data_warehouse_entity()),
            **query_kwargs,
        )

        with self.assertRaises(ValidationError) as context:
            DisallowUnsupportedDataWarehouseSettings().validate(self._context(query))

        self.assertIn(expected_error, str(context.exception))
        self.assertEqual(context.exception.get_codes(), ["data_warehouse_series_unsupported_settings"])

    def test_allows_unsupported_settings_without_data_warehouse_series(self):
        query = RetentionQuery(
            filterTestAccounts=True,
            samplingFactor=0.1,
            retentionFilter=RetentionFilter(totalIntervals=8, aggregationType=AggregationType.COUNT),
        )

        DisallowUnsupportedDataWarehouseSettings().validate(self._context(query))
