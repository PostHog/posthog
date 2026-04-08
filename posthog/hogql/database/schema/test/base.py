import csv
import tempfile
from datetime import datetime
from pathlib import Path

from freezegun import freeze_time
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.temporal.data_imports.sources.stripe.constants import (
    CUSTOMER_RESOURCE_NAME as STRIPE_CUSTOMER_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME,
)

from products.data_warehouse.backend.models import (
    DataWarehouseManagedViewSet,
    DataWarehouseSavedQuery,
    ExternalDataSchema,
)
from products.data_warehouse.backend.test.utils import create_data_warehouse_table_from_csv
from products.data_warehouse.backend.types import DataWarehouseManagedViewSetKind
from products.revenue_analytics.backend.hogql_queries.test.data.structure import (
    STRIPE_CUSTOMER_COLUMNS,
    STRIPE_INVOICE_COLUMNS,
)

TEST_BUCKET_BASE = "test_storage_bucket"
INVOICES_TEST_BUCKET = f"{TEST_BUCKET_BASE}-posthog.revenue_analytics.insights_query_runner.stripe_invoices"
CUSTOMERS_TEST_BUCKET = f"{TEST_BUCKET_BASE}-posthog.revenue_analytics.insights_query_runner.stripe_customers"
_TEST_DATA_DIR = (
    Path(__file__).resolve().parents[5]
    / "products"
    / "revenue_analytics"
    / "backend"
    / "hogql_queries"
    / "test"
    / "data"
)


class RevenueAnalyticsTestBase(ClickhouseTestMixin, BaseTest):
    PURCHASE_EVENT_NAME = "purchase"
    REVENUE_PROPERTY = "revenue"
    SUBSCRIPTION_PROPERTY = "subscription_id"
    QUERY_TIMESTAMP = "2025-05-30"
    EVENT_TIMESTAMP = "2025-05-29"  # One day before the query timestamp
    MODIFIERS = HogQLQueryModifiers(formatCsvAllowDoubleQuotes=True)
    PERSON_ID = "00000000-0000-0000-0000-000000000000"
    DISTINCT_ID = "distinct_id"

    def tearDown(self):
        if hasattr(self, "invoices_cleanup_filesystem"):
            self.invoices_cleanup_filesystem()
        if hasattr(self, "customers_cleanup_filesystem"):
            self.customers_cleanup_filesystem()
        super().tearDown()

    def create_sources(self):
        invoices_csv_path = _TEST_DATA_DIR / "stripe_invoices.csv"
        invoices_table, self.source, credential, _, self.invoices_cleanup_filesystem = (
            create_data_warehouse_table_from_csv(
                invoices_csv_path,
                "stripe_invoice",
                STRIPE_INVOICE_COLUMNS,
                INVOICES_TEST_BUCKET,
                self.team,
            )
        )

        customers_csv_path = _TEST_DATA_DIR / "stripe_customers.csv"
        customers_table, _, _, _, self.customers_cleanup_filesystem = create_data_warehouse_table_from_csv(
            customers_csv_path,
            "stripe_customer",
            STRIPE_CUSTOMER_COLUMNS,
            CUSTOMERS_TEST_BUCKET,
            self.team,
            source=self.source,
            credential=credential,
        )

        _invoices_schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_INVOICE_RESOURCE_NAME,
            source=self.source,
            table=invoices_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

        _customers_schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_CUSTOMER_RESOURCE_NAME,
            source=self.source,
            table=customers_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )


class RevenueAnalyticsManagedViewsetsTestMixin(RevenueAnalyticsTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.mock_flag = patch("posthoganalytics.feature_enabled", return_value=True)
        self.mock_flag.start()

    def tearDown(self) -> None:
        self.mock_flag.stop()
        if hasattr(self, "_materialized_cleanups"):
            for cleanup in self._materialized_cleanups:
                cleanup()
        if hasattr(self, "_temp_csv_files"):
            for csv_path in self._temp_csv_files:
                csv_path.unlink(missing_ok=True)
        super().tearDown()

    def create_and_materialize_viewsets(self):
        with freeze_time(self.QUERY_TIMESTAMP):
            viewset, _ = DataWarehouseManagedViewSet.objects.get_or_create(
                team=self.team, kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS
            )
            viewset.sync_views()
            materialization_csvs = self._get_materialization_csvs()
        self._upload_materialized_csvs(materialization_csvs)

    def _get_materialization_csvs(self):
        materialization_csvs = []
        for saved_query in DataWarehouseSavedQuery.objects.filter(
            team=self.team, managed_viewset__isnull=False
        ).order_by("name"):
            query_text = saved_query.query.get("query", "") if isinstance(saved_query.query, dict) else ""
            if not query_text:
                continue

            response = execute_hogql_query(parse_select(query_text), team=self.team, modifiers=self.MODIFIERS)

            with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(response.columns or [])
                for row in response.results or []:
                    writer.writerow(
                        [value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime) else value for value in row]
                    )
                csv_path = Path(csv_file.name)

            nullable_columns = {}
            for col_name, col_def in (saved_query.columns or {}).items():
                if isinstance(col_def, dict):
                    ch_type = col_def["clickhouse"]
                    if not ch_type.startswith("Nullable("):
                        col_def = {**col_def, "clickhouse": f"Nullable({ch_type})"}
                nullable_columns[col_name] = col_def

            materialization_csvs.append((saved_query, csv_path, nullable_columns))

        return materialization_csvs

    def _upload_materialized_csvs(self, materialization_csvs):
        self._materialized_cleanups = []
        for saved_query, csv_path, nullable_columns in materialization_csvs:
            table, _, _, _, cleanup = create_data_warehouse_table_from_csv(
                csv_path,
                saved_query.name,
                nullable_columns,
                f"{TEST_BUCKET_BASE}-{saved_query.name.replace('.', '_')}",
                self.team,
                source_prefix="",
            )
            self._materialized_cleanups.append(cleanup)
            saved_query.table = table
            saved_query.is_materialized = True
            saved_query.save()
