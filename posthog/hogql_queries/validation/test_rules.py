from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    BreakdownFilter,
    BreakdownType,
    DataWarehouseNode,
    DateRange,
    EventsNode,
    FilterLogicalOperator,
    LifecycleDataWarehouseNode,
    LifecycleQuery,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    TrendsQuery,
)

from posthog.hogql_queries.validation.rules import (
    DisallowUnsupportedDataWarehouseSettings,
    RequireAtLeastOneSeries,
    ValidateDataWarehouseBreakdown,
)
from posthog.hogql_queries.validation.validation import QueryValidationContext

from products.data_warehouse.backend.models import DataWarehouseCredential, DataWarehouseTable


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


class TestValidateDataWarehouseBreakdown(BaseTest):
    def _context(self, query: TrendsQuery) -> QueryValidationContext:
        runner = MagicMock(query=query, team=self.team, user=None)
        return QueryValidationContext(query=query, team=self.team, user=None, runner=runner)

    def _create_data_warehouse_table(self, columns: dict[str, dict[str, str]]) -> str:
        credential = DataWarehouseCredential.objects.create(team=self.team, access_key="key", access_secret="secret")
        table = DataWarehouseTable.objects.create(
            team=self.team,
            name="warehouse_orders",
            columns=columns,
            credential=credential,
            url_pattern="https://bucket.s3/data/*",
        )
        return table.name

    def _query(self, breakdown_filter: BreakdownFilter) -> TrendsQuery:
        return TrendsQuery(
            dateRange=DateRange(date_from="-7d"),
            series=[
                DataWarehouseNode(
                    id="warehouse_orders",
                    table_name="warehouse_orders",
                    timestamp_field="created_at",
                    id_field="order_id",
                    distinct_id_field="customer_id",
                )
            ],
            breakdownFilter=breakdown_filter,
        )

    def _mixed_query(self, breakdown_filter: BreakdownFilter) -> TrendsQuery:
        return TrendsQuery(
            dateRange=DateRange(date_from="-7d"),
            series=[
                EventsNode(event="$pageview"),
                DataWarehouseNode(
                    id="warehouse_orders",
                    table_name="warehouse_orders",
                    timestamp_field="created_at",
                    id_field="order_id",
                    distinct_id_field="customer_id",
                ),
            ],
            breakdownFilter=breakdown_filter,
        )

    @parameterized.expand(
        [
            (
                "non_data_warehouse_breakdown_type",
                BreakdownFilter(breakdown="$browser", breakdown_type=BreakdownType.EVENT),
                None,
                "single data warehouse property",
            ),
            (
                "non_scalar_data_warehouse_breakdown_field",
                BreakdownFilter(breakdown="metadata", breakdown_type=BreakdownType.DATA_WAREHOUSE),
                {
                    "order_id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                    "customer_id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                    "created_at": {"clickhouse": "DateTime64(3, 'UTC')", "hogql": "DateTimeDatabaseField"},
                    "metadata": {"clickhouse": "String", "hogql": "StringJSONDatabaseField"},
                },
                '"metadata" is not a valid data warehouse property for breakdowns.',
            ),
            (
                "scalar_data_warehouse_breakdown_field",
                BreakdownFilter(breakdown="status", breakdown_type=BreakdownType.DATA_WAREHOUSE),
                {
                    "order_id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                    "customer_id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                    "created_at": {"clickhouse": "DateTime64(3, 'UTC')", "hogql": "DateTimeDatabaseField"},
                    "status": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                },
                None,
            ),
        ]
    )
    def test_validates_data_warehouse_breakdown(self, _name, breakdown_filter, columns, expected_error):
        if columns is not None:
            self._create_data_warehouse_table(columns)

        query = self._query(breakdown_filter)

        if expected_error is None:
            ValidateDataWarehouseBreakdown().validate(self._context(query))
            return

        with self.assertRaises(ValidationError) as context:
            ValidateDataWarehouseBreakdown().validate(self._context(query))

        self.assertIn(expected_error, str(context.exception))
        self.assertEqual(context.exception.get_codes(), ["invalid_data_warehouse_breakdown"])

    def test_allows_single_item_data_warehouse_breakdown_list(self):
        self._create_data_warehouse_table(
            {
                "order_id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                "customer_id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                "created_at": {"clickhouse": "DateTime64(3, 'UTC')", "hogql": "DateTimeDatabaseField"},
                "status": {"clickhouse": "String", "hogql": "StringDatabaseField"},
            }
        )

        query = self._query(BreakdownFilter(breakdown=["status"], breakdown_type=BreakdownType.DATA_WAREHOUSE))

        ValidateDataWarehouseBreakdown().validate(self._context(query))

    @parameterized.expand(
        [
            ("event", BreakdownFilter(breakdown=["$browser"], breakdown_type=BreakdownType.EVENT)),
            ("person", BreakdownFilter(breakdown=["email"], breakdown_type=BreakdownType.PERSON)),
        ]
    )
    def test_allows_mixed_series_non_data_warehouse_breakdowns(self, _name, breakdown_filter):
        query = self._mixed_query(breakdown_filter)

        ValidateDataWarehouseBreakdown().validate(self._context(query))

    def test_allows_mixed_series_data_warehouse_breakdown(self):
        self._create_data_warehouse_table(
            {
                "order_id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                "customer_id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                "created_at": {"clickhouse": "DateTime64(3, 'UTC')", "hogql": "DateTimeDatabaseField"},
                "status": {"clickhouse": "String", "hogql": "StringDatabaseField"},
            }
        )

        query = self._mixed_query(BreakdownFilter(breakdown=["status"], breakdown_type=BreakdownType.DATA_WAREHOUSE))

        ValidateDataWarehouseBreakdown().validate(self._context(query))
