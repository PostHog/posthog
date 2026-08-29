from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import AggregationType, BreakdownFilter, EntityType, RetentionFilter, RetentionQuery, TimeWindowMode

from posthog.hogql_queries.insights.retention.retention_validation_rules import (
    DisallowBreakdownsWithDataWarehouse24HourWindows,
    DisallowCumulativeWith24HourWindows,
    DisallowGroupAggregationWithDataWarehouse24HourWindows,
    DisallowPropertyAggregationWith24HourWindows,
    RequireRetentionDataWarehouseEntitiesForCustomAggregationTarget,
)
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
            ("dwh_24h_windows_breakdown", True, TimeWindowMode.FIELD_24_HOUR_WINDOWS, True, True),
            ("dwh_24h_windows_no_breakdown", True, TimeWindowMode.FIELD_24_HOUR_WINDOWS, False, False),
            ("dwh_default_window_breakdown", True, None, True, False),
            ("events_24h_windows_breakdown", False, TimeWindowMode.FIELD_24_HOUR_WINDOWS, True, False),
        ]
    )
    def test_disallow_breakdowns_with_data_warehouse_24h_windows(
        self,
        _name: str,
        use_data_warehouse_entity: bool,
        time_window_mode: TimeWindowMode | None,
        has_breakdown: bool,
        raises_error: bool,
    ) -> None:
        query = RetentionQuery(
            retentionFilter=RetentionFilter(
                timeWindowMode=time_window_mode,
                targetEntity=self._data_warehouse_entity() if use_data_warehouse_entity else None,
            ),
            breakdownFilter=BreakdownFilter(breakdown="$browser", breakdown_type="event") if has_breakdown else None,
        )

        if not raises_error:
            DisallowBreakdownsWithDataWarehouse24HourWindows().validate(self._context(query))
            return

        with self.assertRaises(ValidationError) as context:
            DisallowBreakdownsWithDataWarehouse24HourWindows().validate(self._context(query))

        self.assertIn(
            "Breakdowns are not supported for 24 hour windows with a data warehouse series.", str(context.exception)
        )
        self.assertEqual(
            context.exception.get_codes(), ["retention_data_warehouse_24_hour_windows_breakdowns_unsupported"]
        )

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

    @parameterized.expand(
        [
            ("groups_with_dwh_target_24h", 0, True, False, TimeWindowMode.FIELD_24_HOUR_WINDOWS, True),
            ("groups_with_dwh_return_24h", 0, False, True, TimeWindowMode.FIELD_24_HOUR_WINDOWS, True),
            ("groups_without_dwh_series_24h", 0, False, False, TimeWindowMode.FIELD_24_HOUR_WINDOWS, False),
            ("no_groups_with_dwh_series_24h", None, True, True, TimeWindowMode.FIELD_24_HOUR_WINDOWS, False),
            ("groups_with_dwh_series_default_window", 0, True, True, None, False),
        ]
    )
    def test_disallow_group_aggregation_with_data_warehouse_24h_windows(
        self,
        _name: str,
        group_type_index: int | None,
        dwh_target: bool,
        dwh_return: bool,
        time_window_mode: TimeWindowMode | None,
        raises_error: bool,
    ) -> None:
        query = RetentionQuery(
            aggregation_group_type_index=group_type_index,
            retentionFilter=RetentionFilter(
                timeWindowMode=time_window_mode,
                targetEntity=self._data_warehouse_entity() if dwh_target else None,
                returningEntity=self._data_warehouse_entity() if dwh_return else None,
            ),
        )

        if not raises_error:
            DisallowGroupAggregationWithDataWarehouse24HourWindows().validate(self._context(query))
            return

        with self.assertRaises(ValidationError) as context:
            DisallowGroupAggregationWithDataWarehouse24HourWindows().validate(self._context(query))

        self.assertIn(
            "Group aggregation is not supported for 24 hour windows with a data warehouse series.",
            str(context.exception),
        )
        self.assertEqual(
            context.exception.get_codes(), ["retention_data_warehouse_24_hour_windows_group_aggregation_unsupported"]
        )

    @parameterized.expand(
        [
            ("sum_24h_windows", AggregationType.SUM, "amount", TimeWindowMode.FIELD_24_HOUR_WINDOWS, True),
            ("avg_24h_windows", AggregationType.AVG, "amount", TimeWindowMode.FIELD_24_HOUR_WINDOWS, True),
            ("count_24h_windows", AggregationType.COUNT, None, TimeWindowMode.FIELD_24_HOUR_WINDOWS, False),
            ("sum_without_property_24h", AggregationType.SUM, None, TimeWindowMode.FIELD_24_HOUR_WINDOWS, False),
            ("sum_default_window", AggregationType.SUM, "amount", None, False),
        ]
    )
    def test_disallow_property_aggregation_with_24h_windows(
        self,
        _name: str,
        aggregation_type: AggregationType,
        aggregation_property: str | None,
        time_window_mode: TimeWindowMode | None,
        raises_error: bool,
    ) -> None:
        query = RetentionQuery(
            retentionFilter=RetentionFilter(
                timeWindowMode=time_window_mode,
                aggregationType=aggregation_type,
                aggregationProperty=aggregation_property,
            )
        )

        if not raises_error:
            DisallowPropertyAggregationWith24HourWindows().validate(self._context(query))
            return

        with self.assertRaises(ValidationError) as context:
            DisallowPropertyAggregationWith24HourWindows().validate(self._context(query))

        self.assertIn("Sum and average aggregation are not supported for 24 hour windows.", str(context.exception))
        self.assertEqual(context.exception.get_codes(), ["retention_24_hour_windows_property_aggregation_unsupported"])

    @parameterized.expand(
        [
            ("no_custom_target_events_entities", False, "events", "events", False),
            ("custom_target_events_entities", True, "events", "events", True),
            ("custom_target_unset_entities", True, None, None, True),
            ("custom_target_only_target_dwh", True, "dwh", "events", True),
            ("custom_target_only_returning_dwh", True, "events", "dwh", True),
            ("custom_target_both_dwh", True, "dwh", "dwh", False),
        ]
    )
    def test_require_data_warehouse_entities_for_custom_aggregation_target(
        self,
        _name: str,
        custom_aggregation_target: bool,
        target_entity: str | None,
        returning_entity: str | None,
        raises_error: bool,
    ) -> None:
        def entity(kind: str | None) -> dict[str, str] | None:
            if kind == "dwh":
                return self._data_warehouse_entity()
            if kind == "events":
                return {"id": "$pageview", "type": EntityType.EVENTS}
            return None

        query = RetentionQuery(
            retentionFilter=RetentionFilter(
                customAggregationTarget=custom_aggregation_target,
                targetEntity=entity(target_entity),
                returningEntity=entity(returning_entity),
            )
        )

        if not raises_error:
            RequireRetentionDataWarehouseEntitiesForCustomAggregationTarget().validate(self._context(query))
            return

        with self.assertRaises(ValidationError) as context:
            RequireRetentionDataWarehouseEntitiesForCustomAggregationTarget().validate(self._context(query))

        self.assertIn(
            "Custom entity aggregation target requires both retention entities to be data warehouse entities.",
            str(context.exception),
        )
        self.assertEqual(
            context.exception.get_codes(), ["retention_custom_aggregation_target_requires_data_warehouse_entities"]
        )
